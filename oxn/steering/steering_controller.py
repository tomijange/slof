"""
Purpose: Applies network faults inside Kubernetes pods through the steering sidecar.
Functionality: Adds the steering container from oxn/steering/steering_container.py to the pod template of a
    deployment, and sends it tc netem commands through the API server proxy.
Connection: Kubernetes only. The KubernetesOrchestrator uses it to implement the network fault methods of
    oxn.models.orchestrator.Orchestrator, so treatments never see the sidecar.
"""

import logging
from typing import List

from kubernetes import client
from kubernetes.client.exceptions import ApiException
from kubernetes.client.models.v1_deployment import V1Deployment
from kubernetes.client.models.v1_pod import V1Pod

from oxn.common.errors import OrchestratorException
from oxn.orchestration.cluster_proxy import ClusterProxy
from oxn.orchestration.kubernetes_objects import name_and_namespace, pod_containers

logger = logging.getLogger(__name__)

# Constants
DEFAULT_STEERING_CONTAINER_PORT = 5000
STEERING_REQUEST_TIMEOUT = 30
SIDECAR_CONTAINER_NAME = "oxn-steering-container"
SIDECAR_IMAGE = f"julianlegler/{SIDECAR_CONTAINER_NAME}:latest"


class SteeringController:
    def __init__(
        self,
        api_client: client.AppsV1Api,
        cluster_proxy: ClusterProxy,
        port: int = DEFAULT_STEERING_CONTAINER_PORT,
    ):
        self.api_client = api_client
        self.cluster_proxy = cluster_proxy
        self.session = cluster_proxy.session()
        self.steering_port = port

    @staticmethod
    def has_sidecar(deployment: V1Deployment) -> bool:
        """Return true if the pod template of a deployment has the steering container"""
        return any(container.name == SIDECAR_CONTAINER_NAME for container in pod_containers(deployment))

    def add_sidecar(self, deployment: V1Deployment) -> bool:
        """
        Add the steering container to the pod template of a deployment

        Kubernetes replaces the pods of the deployment afterwards, the caller waits until they are ready.

        Returns:
            False if the deployment already has the steering container, True if it was added

        """
        name, namespace = name_and_namespace(deployment)
        if self.has_sidecar(deployment):
            logger.info(f"Deployment {name} in namespace {namespace} already has {SIDECAR_CONTAINER_NAME}")
            return False

        logger.info(f"Adding {SIDECAR_CONTAINER_NAME} to deployment {name} in namespace {namespace}")
        pod_containers(deployment).append(
            client.V1Container(
                name=SIDECAR_CONTAINER_NAME,
                image=SIDECAR_IMAGE,
                image_pull_policy="Always",
                security_context=client.V1SecurityContext(privileged=True),
            )
        )
        response = self.api_client.patch_namespaced_deployment(name=name, namespace=namespace, body=deployment)
        if not response:
            raise OrchestratorException(
                message=f"Error while patching deployment {name} in namespace {namespace}",
                explanation="The API server returned an empty response",
            )
        return True

    def _send_tc(self, pod: V1Pod, command: str):
        name, namespace = name_and_namespace(pod)
        url = self.cluster_proxy.pod_url(namespace, name, self.steering_port, "tc")
        response = self.session.post(url, json={"cmd": command}, timeout=STEERING_REQUEST_TIMEOUT)

        if response.status_code != 200:
            raise ApiException(status=response.status_code, reason=response.reason)

        # the steering container answers with 200 even if the command failed
        result = response.json()
        if result.get("status") != "ok":
            logger.error(f'Command "{command}" failed on pod {name}: {result.get("message")}')

        return response

    def _send_tc_to_all(self, pods: List[V1Pod], command: str, action: str) -> None:
        try:
            for pod in pods:
                self._send_tc(pod, command)
        except ApiException as e:
            raise OrchestratorException(message=f"Failed to {action}", explanation=str(e))

    def set_network_delay(self, pods: List[V1Pod], interface: str, delay_time: str, jitter: str, correlation: str):
        self._send_tc_to_all(
            pods,
            f"tc qdisc add dev {interface} root netem delay {delay_time} {jitter} {correlation}",
            "set network delay",
        )

    def set_network_loss(self, pods: List[V1Pod], interface: str, loss: float):
        self._send_tc_to_all(pods, f"tc qdisc add dev {interface} root netem loss random {loss}", "set network loss")

    def set_network_corruption(self, pods: List[V1Pod], interface: str, percentage: str, correlation: str):
        self._send_tc_to_all(
            pods,
            f"tc qdisc add dev {interface} root netem corrupt {percentage} {correlation}",
            "set network corruption",
        )

    def remove_netem(self, pods: List[V1Pod], interface: str):
        """Remove the netem queueing discipline, and with it every delay, loss and corruption"""
        self._send_tc_to_all(pods, f"tc qdisc del dev {interface} root netem", "remove network faults")
