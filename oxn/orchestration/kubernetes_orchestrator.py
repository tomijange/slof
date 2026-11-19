"""
Purpose: Runs experiments on Kubernetes.
Functionality: Implements oxn.models.orchestrator.Orchestrator with the Kubernetes API: a workload is a deployment,
    its instances are pods, the SUE's Prometheus and collector are configured through ConfigMaps. Network faults go
    through the steering sidecar, see oxn.steering.steering_controller.SteeringController. Methods that take
    V1Deployment and V1Pod objects are Kubernetes only, for treatments based on oxn.treatments.kubernetes.
Connection: Created by the engine for experiment.orchestrator: kubernetes.
"""

import logging
import time
from typing import Any, Callable, List, Optional, Tuple

import requests
import yaml
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.client.models.v1_deployment import V1Deployment
from kubernetes.client.models.v1_pod import V1Pod
from urllib3.util import Retry

from oxn.common.errors import OrchestratorException, OrchestratorResourceNotFoundException, OxnException
from oxn.common.log import log_exception
from oxn.common.settings import JAEGER_PORT, PROMETHEUS_PORT
from oxn.models.experiment_spec import ExperimentSpec, ServiceReference, Services
from oxn.models.orchestrator import Orchestrator
from oxn.models.workload import WorkloadInstance, WorkloadSelector
from oxn.orchestration.cluster_proxy import ClusterProxy
from oxn.orchestration.deployment import Deployment
from oxn.orchestration.kubernetes_objects import name_and_namespace, pod_containers, pod_selector
from oxn.steering.steering_controller import SteeringController

logger = logging.getLogger(__name__)

SUE_NAMESPACE = "system-under-evaluation"
PROMETHEUS_CONFIGMAP = "prometheus"
PROMETHEUS = WorkloadSelector(namespace=SUE_NAMESPACE, label_selector="app.kubernetes.io/name", label="prometheus")
"""The SUE's Prometheus, whose ConfigMap the scrape values are written to"""
PROMETHEUS_CONFIG_KEY = "prometheus.yml"
OTEL_COLLECTOR_CONFIGMAP = "otel-collector"
OTEL_COLLECTOR_CONFIG_KEY = "relay"
OTEL_COLLECTOR = WorkloadSelector(
    namespace=SUE_NAMESPACE, label_selector="app.kubernetes.io/name", label="opentelemetry-collector"
)
"""The SUE's OpenTelemetry collector, whose ConfigMap the sampling values are written to"""


class KubernetesOrchestrator(Orchestrator):
    def __init__(self, experiment_config: ExperimentSpec):
        logger.info("Initializing Kubernetes orchestrator")
        self.experiment_config = experiment_config
        config.load_kube_config()
        self.kube_client = client.CoreV1Api()
        self.api_client = client.AppsV1Api()
        self.cluster_proxy = ClusterProxy()
        """HTTP access to pods and services, which are not routable from outside the cluster"""
        self.required_services = self.experiment_config.experiment.sue.required
        """The services ready() checks by default"""

        self.steering_controller = SteeringController(api_client=self.api_client, cluster_proxy=self.cluster_proxy)
        """Applies network faults through the steering sidecar"""

        self.deployment = Deployment.from_experiment_spec(self.experiment_config)
        """Deployment of the SUE, None if the spec expects an already running SUE"""

    def _check_required_services(self, required_services: List[ServiceReference]) -> bool:
        """Raise an OxnException unless every service exists"""
        for service in required_services:
            service_name = service.name
            namespace = service.namespace
            try:
                self.kube_client.read_namespaced_service(service_name, namespace)
                logger.debug(f"Service {service_name} in namespace {namespace} is running")
            except ApiException as e:
                raise OxnException(
                    message=f"Service {service_name} in namespace {namespace} is not running but set as a required service",
                    explanation=str(e),
                )
        logger.info(f"All {len(required_services)} required services are running")
        return True

    def orchestrate(self):
        if self.deployment is None:
            logger.info("No deployment in experiment spec, expecting the SUE to be running already")
            return
        self.deployment.deploy()

    def ready(self, expected_services: List[ServiceReference] | None = None, timeout: float = 120) -> bool:
        if expected_services is None:
            expected_services = self.required_services
        return self._check_required_services(expected_services)

    def teardown(self):
        if self.deployment is None:
            logger.info("No deployment in experiment spec, leaving the SUE running")
            return
        self.deployment.teardown()

    def apply_security_context_to_deployment(
        self, label_selector: str, label: str, namespace: str, capabilities: dict
    ) -> Tuple[int, str]:
        """
        Apply a security context to a deployment

        Args:
            label_selector: The label key that selects the deployment
            label: The value of the label
            namespace: The namespace of the deployment
            capabilities: The Linux capabilities, applied to every container

        Returns:
            0 and "Success", or 1 and the error

        """
        try:
            deployment = self.get_deployment(namespace, label_selector, label)
            name, namespace = name_and_namespace(deployment)
            containers = [
                {"name": container.name, "securityContext": {"capabilities": capabilities}}
                for container in pod_containers(deployment)
            ]
            patch_body = {"spec": {"template": {"spec": {"containers": containers}}}}

            logger.debug(f"Patching deployment {name} with {patch_body}")
            if not self.api_client.patch_namespaced_deployment(name=name, namespace=namespace, body=patch_body):
                message = f"Failed to apply security context to deployment '{name}' in namespace '{namespace}'."
                logger.error(message)
                return 1, message
            return 0, "Success"

        except Exception as e:
            log_exception(logger, e, "Failed to apply the security context")
            return 1, str(e)

    def get_address_for_service(self, namespace: str, name: str) -> str:
        """
        Get the cluster IP of a service, or the IP of its first pod for a headless service

        Args:
            namespace: The namespace of the service
            name: The name of the service

        Returns:
            The address of the service

        """

        service = self.kube_client.read_namespaced_service(namespace=namespace, name=name)
        if not service:
            raise OrchestratorResourceNotFoundException(
                message=f"No service found for service {name}",
                explanation="No service found for the given service",
            )
        cluster_ip = service.spec.cluster_ip if service.spec else None

        if cluster_ip is None or cluster_ip == "None":
            logger.info(
                f"Service {name} in namespace {namespace} has no cluster IP. Falling back to pod IP by selecting first pod and receiving its IP"
            )
            labels = (service.metadata.labels if service.metadata else None) or {}
            name_label = labels.get("app.kubernetes.io/name")
            if name_label is None:
                raise OrchestratorResourceNotFoundException(
                    message=f"No address found for service {name}",
                    explanation="The service has no cluster IP and no app.kubernetes.io/name label to find its pods",
                )
            pods = self.kube_client.list_namespaced_pod(
                namespace=namespace, label_selector=f"app.kubernetes.io/name={name_label}"
            )
            if not pods.items:
                raise OrchestratorResourceNotFoundException(
                    message=f"No pods found for service {name}",
                    explanation="No pods found for the given service",
                )
            first_pod = pods.items[0]
            cluster_ip = first_pod.status.pod_ip if first_pod.status else None

        if cluster_ip is None:
            raise OrchestratorResourceNotFoundException(
                message=f"No address found for service {name}",
                explanation="Neither the service nor its first pod has an IP",
            )
        return cluster_ip

    def get_jaeger_url(self, internal: bool = False) -> str:
        return self._service_url(self.get_jaeger_service(), JAEGER_PORT, internal)

    def get_jaeger_service(self):
        """
        Get the Jaeger service from the experiment spec

        Returns:
            The name and namespace of the Jaeger service

        """
        return self._services().jaeger

    def _services(self) -> Services:
        services = self.experiment_config.experiment.services
        if services is None:
            raise OrchestratorException(
                message="The spec has no experiment.services",
                explanation="Prometheus and Jaeger are found through experiment.services",
            )
        return services

    def get_prometheus_url(self, target: str, internal: bool = False) -> str:
        return self._service_url(self.get_prometheus_service(target), PROMETHEUS_PORT, internal)

    def http_session(self, max_retries: Optional[Retry] = None) -> requests.Session:
        return self.cluster_proxy.session(max_retries=max_retries)

    def _service_url(self, service: ServiceReference, port: int, internal: bool) -> str:
        """The cluster DNS name of a service inside the cluster, else its url through the API server proxy"""
        if internal:
            return f"http://{service.name}.{service.namespace}:{port}/"
        return self.cluster_proxy.service_url(service.namespace, service.name, port)

    def get_grafana_service(self) -> ServiceReference:
        """The Grafana service of the spec, which the live dashboards are published to"""
        grafana = self._services().grafana
        if grafana is None:
            raise OrchestratorException(
                message="The spec has no experiment.services.grafana",
                explanation="--dashboard publishes to the Grafana named there, "
                "for oxn setup {name: kube-prometheus-grafana, namespace: oxn-external-monitoring}",
            )
        return grafana

    def get_prometheus_service(self, target):
        """
        Get the Prometheus service of a target from the experiment spec

        Returns:
            The name and namespace of the Prometheus service

        """
        for prometheus_config in self._services().prometheus:
            if prometheus_config.target == target:
                return prometheus_config

        raise OrchestratorException(
            message=f"No Prometheus configuration found for target {target}",
            explanation="No Prometheus configuration found for the given target",
        )

    # Workloads, see Orchestrator

    def get_instances(self, workload: WorkloadSelector) -> List[WorkloadInstance]:
        instances = []
        for pod in self.get_pods(workload.namespace, workload.label_selector, workload.label):
            name, namespace = name_and_namespace(pod)
            phase = (pod.status.phase if pod.status else None) or "Unknown"
            instances.append(WorkloadInstance(name=name, namespace=namespace, state=phase, running=phase == "Running"))
        return instances

    def kill_instance(self, instance: WorkloadInstance) -> None:
        self.kill_pod(client.V1Pod(metadata=client.V1ObjectMeta(name=instance.name, namespace=instance.namespace)))

    def get_replicas(self, workload: WorkloadSelector) -> int:
        spec = self.get_workload_deployment(workload).spec
        # Kubernetes runs one replica if the spec sets none
        return spec.replicas if spec and spec.replicas is not None else 1

    def scale(self, workload: WorkloadSelector, replicas: int) -> None:
        deployment = self.get_workload_deployment(workload)
        if self.scale_deployment(deployment, replicas) is None:
            raise OrchestratorException(
                message=f"Failed to scale the deployment with {workload} to {replicas}",
                explanation="The API server returned an empty response",
            )

    def restart(self, workload: WorkloadSelector) -> None:
        self.restart_pods_of_deployment(self.get_workload_deployment(workload))

    def is_ready(self, workload: WorkloadSelector) -> bool:
        return self.is_deployment_ready(self.get_workload_deployment(workload))

    def get_environment_variable(self, workload: WorkloadSelector, name: str) -> Optional[str]:
        for env_var in self._main_container(self.get_workload_deployment(workload)).env or []:
            if env_var.name == name:
                return env_var.value
        return None

    def set_environment_variable(self, workload: WorkloadSelector, name: str, value: str) -> None:
        # the deployment is read again on every try, a patch of an outdated object fails
        for i in range(0, 10):
            deployment = self.get_workload_deployment(workload)
            deployment_name, namespace = name_and_namespace(deployment)
            container = self._main_container(deployment)
            if container.env is None:
                container.env = []
            for env_var in container.env:
                if env_var.name == name:
                    env_var.value = value
                    break
            else:
                container.env.append(client.V1EnvVar(name=name, value=value))
            try:
                self.api_client.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=deployment)
                return
            except ApiException as e:
                logger.error(
                    f"Error while updating the deployment with {workload}: {e.body}. Waiting for 1 second and retrying. Retry {i}"
                )
                time.sleep(1)

        raise OrchestratorException(
            message=f"Error while updating the deployment with {workload}",
            explanation=f"Setting the environment variable {name} failed 10 times",
        )

    @staticmethod
    def _main_container(deployment: V1Deployment) -> client.V1Container:
        """The first container of the pod template, the one environment variables are read from and written to"""
        containers = pod_containers(deployment)
        if not containers:
            raise OrchestratorException(
                message=f"Deployment {name_and_namespace(deployment)[0]} has no containers",
                explanation="Its pod template lists none",
            )
        return containers[0]

    # Network faults, through the steering sidecar

    def prepare_network_faults(self, workload: WorkloadSelector) -> None:
        deployment = self.get_workload_deployment(workload)
        if self.steering_controller.add_sidecar(deployment):
            self._wait_until_deployment_ready(deployment, "adding the steering container")

    def set_network_delay(
        self, workload: WorkloadSelector, interface: str, delay_time: str, jitter: str, correlation: str
    ) -> None:
        self.steering_controller.set_network_delay(
            self._workload_pods(workload), interface, delay_time, jitter, correlation
        )

    def set_network_loss(self, workload: WorkloadSelector, interface: str, loss: float) -> None:
        self.steering_controller.set_network_loss(self._workload_pods(workload), interface, loss)

    def set_network_corruption(
        self, workload: WorkloadSelector, interface: str, percentage: str, correlation: str
    ) -> None:
        self.steering_controller.set_network_corruption(
            self._workload_pods(workload), interface, percentage, correlation
        )

    def remove_network_faults(self, workload: WorkloadSelector, interface: str) -> None:
        self.steering_controller.remove_netem(self._workload_pods(workload), interface)

    def _workload_pods(self, workload: WorkloadSelector) -> List[V1Pod]:
        pods = self.pods_of_deployment(self.get_workload_deployment(workload))
        if not pods:
            raise OrchestratorResourceNotFoundException(
                message=f"No pods found for the deployment with {workload}",
                explanation="The deployment has no pods to apply the network fault to",
            )
        return pods

    # Kubernetes only

    def get_workload_deployment(self, workload: WorkloadSelector) -> V1Deployment:
        """Return the deployment of a workload"""
        return self.get_deployment(workload.namespace, workload.label_selector, workload.label)

    def get_deployment(self, namespace, label_selector, label) -> V1Deployment:
        """
        Get the deployment for a service

        Args:
            namespace: The namespace of the service
            label_selector: The label selector for the service
            label: The label of the service

        Returns:
            The deployment of the service

        """
        deployments = self.api_client.list_namespaced_deployment(namespace, label_selector=f"{label_selector}={label}")
        if not deployments.items:
            raise OrchestratorResourceNotFoundException(
                message=f"No deployments found for service {label}",
                explanation="No deployments found for the given service",
            )
        if len(deployments.items) > 1:
            raise OrchestratorException(
                message=f"Multiple deployments found for service {label}",
                explanation="Multiple deployments found for the given service",
            )
        return deployments.items[0]

    def scale_deployment(self, deployment: V1Deployment, replicas: int):
        """
        Scale a deployment

        Args:
            deployment: The deployment to scale
            replicas: The number of replicas

        """
        name, namespace = name_and_namespace(deployment)
        return self.api_client.patch_namespaced_deployment_scale(
            name=name, namespace=namespace, body={"spec": {"replicas": replicas}}
        )

    def get_pods(self, namespace, label_selector, label) -> List[V1Pod]:
        """
        Get the pods for a service

        Args:
            namespace: The namespace of the service
            label_selector: The label selector for the service
            label: The label of the service

        Returns:
            The pods of the service

        """
        pods = self.kube_client.list_namespaced_pod(namespace, label_selector=f"{label_selector}={label}")
        if not pods.items:
            raise OrchestratorResourceNotFoundException(
                message=f"No pods found with the given label selector {label_selector}={label}",
                explanation="No pods found with the given label selector {label_selector}={label}",
            )
        return pods.items

    def kill_pod(self, pod: V1Pod):
        """
        Kill a pod

        Args:
            pod: The pod to kill

        """
        name, namespace = name_and_namespace(pod)
        try:
            return self.kube_client.delete_namespaced_pod(name=name, namespace=namespace, grace_period_seconds=0)
        except ApiException as e:
            raise OrchestratorException(
                message=f"Error while deleting pod {name} in namespace {namespace}: {e.body}",
                explanation=str(e),
            )

    def is_deployment_ready(self, deployment: V1Deployment) -> bool:
        """
        Check if a deployment is ready

        Args:
            deployment: The deployment to check

        Returns:
            True if the deployment is ready, False otherwise

        """
        name, namespace = name_and_namespace(deployment)
        # the status of the given object is outdated
        status = self.api_client.read_namespaced_deployment_status(name=name, namespace=namespace).status
        if status is None:
            return False
        replicas = status.replicas or 0
        return status.ready_replicas == replicas and replicas > 0

    def get_prometheus_scrape_values(self) -> Tuple[str, str, str]:
        """Read the global scrape interval, evaluation interval and scrape timeout from the Prometheus ConfigMap"""
        _, prometheus_config = self._read_configmap_yaml(PROMETHEUS_CONFIGMAP, PROMETHEUS_CONFIG_KEY)
        scrape = prometheus_config["global"]
        return scrape["scrape_interval"], scrape["evaluation_interval"], scrape["scrape_timeout"]

    def set_prometheus_scrape_values(self, scrape_interval: str, evaluation_interval: str, scrape_timeout: str) -> None:
        """Write the global scrape values to the Prometheus ConfigMap and restart Prometheus"""
        configmap, prometheus_config = self._read_configmap_yaml(PROMETHEUS_CONFIGMAP, PROMETHEUS_CONFIG_KEY)
        prometheus_config["global"].update(
            scrape_interval=scrape_interval, evaluation_interval=evaluation_interval, scrape_timeout=scrape_timeout
        )
        self._write_configmap_yaml(PROMETHEUS_CONFIGMAP, configmap, PROMETHEUS_CONFIG_KEY, prometheus_config)
        self.restart(PROMETHEUS)

    def get_otel_collector_probabilistic_sampling_values(self) -> Tuple[str, str]:
        """Read the sampling percentage and hash seed of the probabilistic sampler from the collector ConfigMap"""
        _, collector_config = self._read_configmap_yaml(OTEL_COLLECTOR_CONFIGMAP, OTEL_COLLECTOR_CONFIG_KEY)
        sampler = collector_config["processors"]["probabilistic_sampler"]
        return sampler["sampling_percentage"], sampler["hash_seed"]

    def set_otel_collector_probabilistic_sampling_values(self, sampling_percentage: float, hash_seed: int) -> None:
        """
        Write the sampling percentage to the collector ConfigMap, in proportional mode, and restart the collector

        The hash seed is not written, the sampler keeps the one from the ConfigMap.
        """
        configmap, collector_config = self._read_configmap_yaml(OTEL_COLLECTOR_CONFIGMAP, OTEL_COLLECTOR_CONFIG_KEY)
        sampler = collector_config["processors"]["probabilistic_sampler"]
        sampler["sampling_percentage"] = float(sampling_percentage)
        sampler["mode"] = "proportional"
        self._write_configmap_yaml(OTEL_COLLECTOR_CONFIGMAP, configmap, OTEL_COLLECTOR_CONFIG_KEY, collector_config)
        # TODO: it seems there might be a way to reload config maps without restarting the pods in some cases. This should be investigated (https://kubernetes.io/docs/concepts/configuration/configmap/#mounted-configmaps-are-updated-automatically)
        self.restart(OTEL_COLLECTOR)

    def _read_configmap_yaml(self, name: str, key: str) -> Tuple[client.V1ConfigMap, dict]:
        """Read a ConfigMap of the SUE and parse the YAML file stored under key"""
        try:
            configmap = self.kube_client.read_namespaced_config_map(name=name, namespace=SUE_NAMESPACE)
        except ApiException as e:
            raise OrchestratorException(
                message=f"Error while reading ConfigMap {name} in namespace {SUE_NAMESPACE}: {e.body}",
                explanation=str(e),
            )
        content = (configmap.data or {}).get(key)
        if not content:
            raise OrchestratorException(
                message=f"{key} not found in ConfigMap {name} in namespace {SUE_NAMESPACE}",
                explanation=f"The ConfigMap has no key {key}",
            )
        return configmap, yaml.safe_load(content)

    def _write_configmap_yaml(self, name: str, configmap: client.V1ConfigMap, key: str, content: dict) -> None:
        """Store content as YAML under key in a ConfigMap read with _read_configmap_yaml"""
        configmap.data = {**(configmap.data or {}), key: yaml.dump(content, default_flow_style=False)}
        try:
            self.kube_client.patch_namespaced_config_map(name=name, namespace=SUE_NAMESPACE, body=configmap)
        except ApiException as e:
            raise OrchestratorException(
                message=f"Error while updating ConfigMap {name} in namespace {SUE_NAMESPACE}: {e.body}",
                explanation=str(e),
            )
        logger.info(f"ConfigMap {name} updated successfully.")

    def restart_pods_of_deployment(self, deployment: V1Deployment):
        """
        Restart the pods of a deployment and wait until it is ready

        Args:
            deployment: The deployment to restart the pods for

        """
        name, namespace = name_and_namespace(deployment)
        pods = self.pods_of_deployment(deployment)
        if not pods:
            raise OrchestratorResourceNotFoundException(
                message=f"No pods found for deployment {name}",
                explanation="No pods found for the given deployment",
            )

        for pod in pods:
            self.kill_pod(pod)
            logger.info(f"Pod {name_and_namespace(pod)[0]} in namespace {namespace} has been killed because of restart")

        self._wait_until_deployment_ready(deployment, "restart")

    def _wait_until_deployment_ready(self, deployment: V1Deployment, reason: str) -> None:
        """Wait up to about 90 seconds for a deployment to be ready after a change that replaces its pods"""
        name, _ = name_and_namespace(deployment)
        time.sleep(4)
        for i in range(0, 10):
            if self.is_deployment_ready(deployment):
                logger.info(f"Deployment {name} is ready after {reason}")
                return
            time.sleep(i * 2)
            logger.info(f"Waiting for deployment {name} to be ready after {reason}. Retry {i}")
        logger.warning(f"Deployment {name} is still not ready after {reason}")

    def pods_of_deployment(self, deployment: V1Deployment) -> List[V1Pod]:
        """
        List the pods that the selector of a deployment matches

        Args:
            deployment: The deployment to list the pods for

        """
        _, namespace = name_and_namespace(deployment)
        return self.kube_client.list_namespaced_pod(namespace=namespace, label_selector=pod_selector(deployment)).items

    def deploy_yaml(self, yaml_str: str):
        """
        Create the Deployment, ConfigMap or Service a manifest describes, replacing one with the same name

        Args:
            yaml_str: The manifest

        """
        body = self._load_manifest(yaml_str)
        create, delete, kind = self._manifest_calls(body)
        name, namespace = body["metadata"]["name"], body["metadata"]["namespace"]
        try:
            return create(body=body, namespace=namespace)
        except ApiException as e:
            if "already exists" not in str(e):
                raise OrchestratorException(message=f"Error while deploying {kind} {name}", explanation=str(e))
        logger.warning(f"{kind} {name} already exists in namespace {namespace}. Deleting it and creating it again.")
        try:
            delete(name=name, namespace=namespace)
            response = create(body=body, namespace=namespace)
        except ApiException as e:
            raise OrchestratorException(message=f"Error while deploying {kind} {name}", explanation=str(e))
        logger.info(f"{kind} {name} in namespace {namespace} has been deleted and created again successfully")
        return response

    def delete_yaml(self, yaml_str: str):
        """
        Delete the Deployment, ConfigMap or Service a manifest describes

        Args:
            yaml_str: The manifest

        """
        body = self._load_manifest(yaml_str)
        _, delete, kind = self._manifest_calls(body)
        name = body["metadata"]["name"]
        try:
            return delete(name=name, namespace=body["metadata"]["namespace"])
        except ApiException as e:
            raise OrchestratorException(message=f"Error while deleting {kind} {name}", explanation=str(e))

    @staticmethod
    def _load_manifest(yaml_str: str) -> dict:
        try:
            body = yaml.safe_load(yaml_str)
        except yaml.YAMLError as e:
            raise OrchestratorException(message="Error while loading yaml file", explanation=str(e))
        if not isinstance(body, dict):
            raise OrchestratorException(message="Error while loading yaml file", explanation="It holds no manifest")
        return body

    def _manifest_calls(self, body: dict) -> Tuple[Callable[..., Any], Callable[..., Any], str]:
        """Return the create and delete calls of the API for the kind of a manifest, and the kind"""
        kind = body.get("kind")
        calls = {
            "Deployment": (self.api_client.create_namespaced_deployment, self.api_client.delete_namespaced_deployment),
            "ConfigMap": (self.kube_client.create_namespaced_config_map, self.kube_client.delete_namespaced_config_map),
            "Service": (self.kube_client.create_namespaced_service, self.kube_client.delete_namespaced_service),
        }
        if kind not in calls:
            raise OrchestratorException(
                message=f"Cannot deploy manifests of kind {kind}",
                explanation=f"Supported kinds are {', '.join(calls)}",
            )
        create, delete = calls[kind]
        return create, delete, kind
