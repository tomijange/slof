import importlib
import importlib.util
import logging
import os
from importlib.machinery import ModuleSpec

import requests
from gevent.pool import Group
from jinja2 import Environment as JinjaEnvironment
from jinja2 import FileSystemLoader
from locust.env import Environment
from locust.log import setup_logging
from locust.stats import stats_history, stats_printer

import oxn.common.utils as utils
from locust import HttpUser
from oxn.common.errors import LocustException
from oxn.models.experiment_spec import ExperimentSpec
from oxn.models.load_generator import BaseLoadGenerator
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class LocustKubernetesLoadgenerator(BaseLoadGenerator):
    """
    Locust loader for oxn.
    This loads the locust file and either runs the load locally or deploys
    Kubernetes resources using dynamic templating (when a target is specified).
    """

    def __init__(self, orchestrator: KubernetesOrchestrator, config: ExperimentSpec):
        super().__init__(orchestrator, config)
        self.run_time: int = 0  # total desired run time (in seconds)
        self.locust_files = None  # list of locust file definitions
        self._read_config()
        self.greenlets = Group()

    def _read_config(self):
        """Read the load generation section of an experiment specification."""
        loadgen_section = self.config.experiment.loadgen
        self.run_time = int(utils.time_string_to_seconds(loadgen_section.run_time))
        self.locust_files = loadgen_section.locust_files

        self.target = loadgen_section.target

        self.max_users = loadgen_section.max_users
        self.spawn_rate = loadgen_section.spawn_rate

        # Default to local host if no target specified.
        self.base_address = "localhost"
        self.port = 8080

        if self.target:
            # When a target is provided, we expect the orchestrator to be a KubernetesOrchestrator.
            assert isinstance(self.orchestrator, KubernetesOrchestrator), (
                "Orchestrator must be KubernetesOrchestrator if target is specified"
            )
            self.base_address = self.orchestrator.get_address_for_service(
                name=self.target.name, namespace=self.target.namespace
            )
            self.port = self.target.port

        logger.info(f"Base address for load generation set to {self.base_address}:{self.port}")

        # In local mode, we create a Locust environment.
        if not self.target:
            self.env = Environment(user_classes=[], host=f"http://{self.base_address}:{self.port}")
            self.env.create_local_runner()

        # Load locust files locally (to register user classes) even if running in Kubernetes.
        for locust_file in self.locust_files:
            path = locust_file.path
            locust_module = self._load_locust_file(path)
            for user_class in dir(locust_module):
                user_class_instance = getattr(locust_module, user_class)
                if (
                    isinstance(user_class_instance, type)
                    and issubclass(user_class_instance, HttpUser)
                    and user_class_instance is not HttpUser
                ):
                    if not self.target:
                        assert self.env is not None
                        self.env.user_classes.append(user_class_instance)
                    logger.info(f"Added user class {user_class_instance.__name__} from {path}")

    def _load_locust_file(self, path):
        """Load a locust file from the specified path."""
        spec = importlib.util.spec_from_file_location("locustfile", path)
        if not spec:
            raise LocustException(f"Could not load locust file from {path}")
        assert isinstance(spec, ModuleSpec)
        assert spec.loader is not None
        locustfile = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(locustfile)
        return locustfile

    def _generate_locustfile_content(self) -> str:
        """
        Generate the content for the locustfile. For simplicity, the content is taken from
        the first locust file provided. Extend this if merging multiple files is needed.
        """
        if self.locust_files and len(self.locust_files) > 0:
            path = self.locust_files[0].path
            with open(path, "r") as f:
                return f.read()
        return ""

    def _generate_k8s_yaml(self) -> dict:
        """
        Generate Kubernetes YAML manifests using Jinja2 templates loaded from files.
        Returns a dict with keys for each YAML resource.
        """
        locustfile_content = self._generate_locustfile_content()

        # Define the directory containing the templates.
        templates_path = os.path.join(os.path.dirname(__file__), "../../locust/kubernetes")
        jinja_env = JinjaEnvironment(loader=FileSystemLoader(templates_path), trim_blocks=True, lstrip_blocks=True)

        # Load each template file.
        configmap_template = jinja_env.get_template("configmap.yaml")
        master_template = jinja_env.get_template("master.yaml")
        worker_template = jinja_env.get_template("worker.yaml")
        service_template = jinja_env.get_template("service.yaml")

        # Render the templates with dynamic parameters.
        configmap_yaml = configmap_template.render(locustfile_content=locustfile_content)
        master_yaml = master_template.render(
            max_users=self.max_users,
            spawn_rate=self.spawn_rate,
            run_time=self.run_time,
            base_address=self.base_address,
            port=self.port,
        )
        worker_yaml = worker_template.render(worker_replicas=2, master_host="locust-master")

        return {
            "configmap": configmap_yaml,
            "master": master_yaml,
            "worker": worker_yaml,
            "service": service_template.render(),
        }

    def start(self):
        """Start the load generation or deploy the Kubernetes resources if target is specified."""
        logger.info(
            f"Starting load generation against {self.base_address}:{self.port} with {self.max_users} users, "
            f"spawn rate {self.spawn_rate}/s, run time {self.run_time}s"
        )
        if self.target:
            # Generate and deploy YAMLs on Kubernetes.
            self.resources = self._generate_k8s_yaml()
            assert isinstance(self.orchestrator, KubernetesOrchestrator), "Orchestrator must be KubernetesOrchestrator"
            for name in ("configmap", "master", "worker", "service"):
                self.orchestrator.deploy_yaml(self.resources[name])
            logger.info("Deployed locust master and worker pods on Kubernetes.")
        else:
            # Local runner mode.
            # replaces the handlers of the root logger, so only do this if locust runs in this process
            setup_logging("INFO", None)
            assert self.env is not None, "Locust environment must be initialized before starting"
            assert self.env.runner is not None, "Locust runner must be initialized before starting"
            self.env.runner.start(self.max_users, self.spawn_rate)
            self.greenlets.spawn(stats_printer(self.env.stats))
            self.greenlets.spawn(stats_history, self.env.runner)

        self.loadgen_start_time = utils.utc_timestamp()

    def stop(self):
        """Stop load generation or clean up Kubernetes resources."""
        if self.target:
            self.stats = self.get_stats_from_master()
            requests_sent = sum(entry["num_requests"] for entry in self.stats["stats"])
            failures = sum(entry["num_failures"] for entry in self.stats["stats"])
            logger.info(f"Load generation sent {requests_sent} requests, {failures} failed")
            assert isinstance(self.orchestrator, KubernetesOrchestrator), "Orchestrator must be KubernetesOrchestrator"
            for name in ("configmap", "master", "worker", "service"):
                self.orchestrator.delete_yaml(self.resources[name])
            logger.info("Cleaned up Kubernetes resources for the locust load test.")
        else:
            if self.env and self.env.runner:
                self.env.runner.quit()
                self.greenlets.join(timeout=30)  # Ensure no hanging threads.
                self.greenlets.kill()

        self.loadgen_stop_time = utils.utc_timestamp()

    def kill(self):
        """Kill all spawned greenlets and stop the runner if needed."""
        self.greenlets.kill()
        if self.env and self.env.runner:
            self.env.runner.quit()

    def get_stats_from_master(self):
        """Get the stats from the locust master."""
        if not self.target:
            return None

        assert isinstance(self.orchestrator, KubernetesOrchestrator), "Orchestrator must be KubernetesOrchestrator"
        # Build the URL for the stats endpoint.
        cluster_proxy = self.orchestrator.cluster_proxy
        url = cluster_proxy.service_url(self.target.namespace, "locust-master", 8089, "stats/requests")
        try:
            with cluster_proxy.session() as session:
                response = session.get(url, timeout=5)
            response.raise_for_status()
            stats = response.json()  # Convert JSON response into Python dict.
            return stats
        except requests.RequestException as e:
            raise Exception(f"Error fetching stats from master: {e}")
