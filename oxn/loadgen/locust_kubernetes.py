import importlib
import importlib.util
import logging
import os
from importlib.machinery import ModuleSpec
from typing import Dict, List, Optional

import requests
from gevent.pool import Group
from jinja2 import Environment as JinjaEnvironment
from jinja2 import FileSystemLoader
from locust.env import Environment
from locust.log import setup_logging
from locust.stats import stats_history, stats_printer

import oxn.common.utils as utils
from locust import HttpUser
from oxn.common.errors import LocustException, OxnException
from oxn.common.log import log_exception
from oxn.common.settings import LOCUST_IMAGE
from oxn.models.experiment_spec import ExperimentSpec
from oxn.models.load_generator import BaseLoadGenerator
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "kubernetes")
"""The Jinja templates of the in-cluster Locust"""
METRICS_FILE = os.path.join(TEMPLATES_DIR, "oxn_metrics.py")
"""Shipped with the locust files of every in-cluster Locust, it adds /metrics to the master"""
METRICS_TARGET = "oxn"
"""The Prometheus target that scrapes the metrics of the in-cluster Locust"""
LOCUST_DIR = "/home/locust"
"""Where the pods mount the ConfigMap with the locust files, the working directory of the locustio/locust image"""


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
        self.data_files = loadgen_section.data_files
        self.namespace = loadgen_section.namespace
        self.deployed: List[str] = []
        """The manifests start() applied in the cluster, removed by stop() and kill()"""

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

    def _shipped_files(self) -> Dict[str, str]:
        """
        The locust files and data files by file name, as the ConfigMap mounts them into LOCUST_DIR of the pods

        All locust files run, so their user classes need distinct names. Data files are read by the locust files, which
        find them next to themselves.
        """
        assert self.locust_files, "The spec lists no locust files"
        files: Dict[str, str] = {}
        for path in [locust_file.path for locust_file in self.locust_files] + list(self.data_files) + [METRICS_FILE]:
            name = os.path.basename(path)
            if name in files:
                raise LocustException(f"Two load generation files are named {name}, the pods need distinct names")
            with open(path, "r") as fp:
                files[name] = fp.read()
        return files

    def _locustfile_paths(self) -> str:
        """The -f argument of master and workers: every locust file in the order of the spec, then the metrics module"""
        assert self.locust_files, "The spec lists no locust files"
        paths = [locust_file.path for locust_file in self.locust_files] + [METRICS_FILE]
        return ",".join(f"{LOCUST_DIR}/{os.path.basename(path)}" for path in paths)

    def _generate_k8s_yaml(self, service_monitor_labels: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        The manifests of the in-cluster Locust, rendered from the templates in TEMPLATES_DIR, in the order to apply them

        With service_monitor_labels, they include a ServiceMonitor with these labels, so Prometheus scrapes the
        metrics of the master.
        """
        jinja_env = JinjaEnvironment(loader=FileSystemLoader(TEMPLATES_DIR), trim_blocks=True, lstrip_blocks=True)
        common = {"namespace": self.namespace, "image": LOCUST_IMAGE}
        manifests = {
            "configmap": jinja_env.get_template("configmap.yaml").render(files=self._shipped_files(), **common),
            "master": jinja_env.get_template("master.yaml").render(
                max_users=self.max_users,
                spawn_rate=self.spawn_rate,
                run_time=self.run_time,
                base_address=self.base_address,
                port=self.port,
                locustfiles=self._locustfile_paths(),
                **common,
            ),
            "worker": jinja_env.get_template("worker.yaml").render(
                worker_replicas=2, master_host="locust-master", locustfiles=self._locustfile_paths(), **common
            ),
            "service": jinja_env.get_template("service.yaml").render(**common),
        }
        if service_monitor_labels is not None:
            manifests["servicemonitor"] = jinja_env.get_template("servicemonitor.yaml").render(
                labels=service_monitor_labels, **common
            )
        return manifests

    def start(self):
        """Start the load generation or deploy the Kubernetes resources if target is specified."""
        logger.info(
            f"Starting load generation against {self.base_address}:{self.port} with {self.max_users} users, "
            f"spawn rate {self.spawn_rate}/s, run time {self.run_time}s"
        )
        if self.target:
            assert isinstance(self.orchestrator, KubernetesOrchestrator), "Orchestrator must be KubernetesOrchestrator"
            labels = self.orchestrator.get_service_monitor_labels(METRICS_TARGET)
            if labels is None:
                logger.warning(
                    f"No Prometheus operator manages the Prometheus of target {METRICS_TARGET}, "
                    "so the metrics of Locust are not scraped"
                )
            self.resources = self._generate_k8s_yaml(service_monitor_labels=labels)
            self.orchestrator.ensure_namespace(self.namespace)
            for manifest in self.resources.values():
                # appended first, so kill() also removes a resource whose creation failed halfway
                self.deployed.append(manifest)
                self.orchestrator.deploy_yaml(manifest)
            logger.info(f"Deployed locust master and worker pods in namespace {self.namespace}")
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
            self._remove_deployed()
            logger.info(f"Removed the locust pods from namespace {self.namespace}")
        else:
            if self.env and self.env.runner:
                self.env.runner.quit()
                self.greenlets.join(timeout=30)  # Ensure no hanging threads.
                self.greenlets.kill()

        self.loadgen_stop_time = utils.utc_timestamp()

    def kill(self):
        """
        Stop the load at once, after an error or ctrl-c

        Removes the in-cluster Locust, which runs outside the SUE's namespace and would otherwise outlive the SUE and
        send load to the next run.
        """
        self.greenlets.kill()
        if self.env and self.env.runner:
            self.env.runner.quit()
        if self.target and self.deployed:
            self._remove_deployed(ignore_errors=True)
            logger.info(f"Removed the locust pods from namespace {self.namespace}")

    def _remove_deployed(self, ignore_errors: bool = False) -> None:
        """Delete the manifests start() applied, in reverse order"""
        assert isinstance(self.orchestrator, KubernetesOrchestrator), "Orchestrator must be KubernetesOrchestrator"
        while self.deployed:
            manifest = self.deployed.pop()
            try:
                self.orchestrator.delete_yaml(manifest)
            except OxnException as e:
                if not ignore_errors:
                    raise
                log_exception(logger, e, "Could not remove a locust resource, proceeding", level=logging.WARNING)

    def get_stats_from_master(self):
        """Get the stats from the locust master."""
        if not self.target:
            return None

        assert isinstance(self.orchestrator, KubernetesOrchestrator), "Orchestrator must be KubernetesOrchestrator"
        # Build the URL for the stats endpoint.
        cluster_proxy = self.orchestrator.cluster_proxy
        url = cluster_proxy.service_url(self.namespace, "locust-master", 8089, "stats/requests")
        try:
            with cluster_proxy.session() as session:
                response = session.get(url, timeout=5)
            response.raise_for_status()
            stats = response.json()  # Convert JSON response into Python dict.
            return stats
        except requests.RequestException as e:
            raise Exception(f"Error fetching stats from master: {e}")
