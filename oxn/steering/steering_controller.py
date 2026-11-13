from calendar import c
import logging
from typing import List

from kubernetes import client, config
from kubernetes.stream import stream
from kubernetes.client.exceptions import ApiException
from kubernetes.client.models.v1_deployment import V1Deployment
from kubernetes.client.models.v1_pod import V1Pod

from oxn.common.errors import OrchestratorException
from oxn.orchestration.cluster_proxy import ClusterProxy

logger = logging.getLogger(__name__)

# Constants
DEFAULT_STEERING_CONTAINER_PORT = 5000
STEERING_REQUEST_TIMEOUT = 30

class SteeringController:

    def __init__(self, kube_client: client.CoreV1Api, api_client: client.ApiClient, cluster_proxy: ClusterProxy, port: int = DEFAULT_STEERING_CONTAINER_PORT):
        self.kube_client = kube_client
        self.api_client = api_client
        self.cluster_proxy = cluster_proxy
        self.session = cluster_proxy.session()
        self.steering_port = port

    def _send_tc(self, pod: V1Pod, command: str):
        assert pod.metadata
        assert pod.metadata.name is not None
        assert pod.metadata.namespace is not None

        url = self.cluster_proxy.pod_url(pod.metadata.namespace, pod.metadata.name, self.steering_port, 'tc')
        response = self.session.post(url, json={'cmd': command}, timeout=STEERING_REQUEST_TIMEOUT)

        if response.status_code != 200:
            raise ApiException(status=response.status_code, reason=response.reason)

        # the steering container answers with 200 even if the command failed
        result = response.json()
        if result.get('status') != 'ok':
            logger.error(f'Command "{command}" failed on pod {pod.metadata.name}: {result.get("message")}')

        return response

    def send_tc_add_network_delay(self, pod: V1Pod, interface: str, delay_time: str, jitter: str, correlation: str):
        return self._send_tc(pod, f'tc qdisc add dev {interface} root netem delay {delay_time} {jitter} {correlation}')

    def send_tc_remove_network_delay(self, pod: V1Pod, interface: str):
        return self._send_tc(pod, f'tc qdisc del dev {interface} root netem')

    def send_tc_add_network_loss(self, pod: V1Pod, interface: str, loss: str):
        return self._send_tc(pod, f'tc qdisc add dev {interface} root netem loss random {loss}')

    def send_tc_remove_network_loss(self, pod: V1Pod, interface: str):
        return self._send_tc(pod, f'tc qdisc del dev {interface} root netem')

    def send_tc_add_network_corruption(self, pod: V1Pod, interface: str, percentage: str, correlation: str):
        return self._send_tc(pod, f'tc qdisc add dev {interface} root netem corrupt {percentage} {correlation}')

    def send_tc_remove_network_corruption(self, pod: V1Pod, interface: str):
        return self._send_tc(pod, f'tc qdisc del dev {interface} root netem')

    def set_network_delay(self, pods: List[V1Pod], interface: str, delay_time: str, jitter: str, correlation: str):
        try:
            for pod in pods:
                self.send_tc_add_network_delay(pod, interface, delay_time, jitter, correlation)
        except OrchestratorException as e:
            raise OrchestratorException(f'Failed to set network delay: {e}')
        
        return True
    
    
    def remove_network_delay(self, pods: List[V1Pod], interface: str):
        try:
            for pod in pods:
                self.send_tc_remove_network_delay(pod, interface)
        except OrchestratorException as e:
            raise OrchestratorException(f'Failed to reset network delay: {e}')
        
        return True
        
    def set_network_loss(self, pods: List[V1Pod], interface: str, loss: str):
        try:
            for pod in pods:
                self.send_tc_add_network_loss(pod, interface, loss)
        except OrchestratorException as e:
            raise OrchestratorException(f'Failed to set network loss: {e}')
        
        return True
        
    def remove_network_loss(self, pods: List[V1Pod], interface: str):
        try:
            for pod in pods:
                self.send_tc_remove_network_delay(pod, interface)
        except OrchestratorException as e:
            raise OrchestratorException(f'Failed to reset network loss: {e}')
        
        return True
    
    def set_network_corruption(self, pods: List[V1Pod], interface: str, percentage, correlation):
        try:
            for pod in pods:
                self.send_tc_add_network_corruption(pod, interface, percentage, correlation)
        except OrchestratorException as e:
            raise OrchestratorException(f'Failed to set network corruption: {e}')
        
        return True
    
    def remove_network_corruption(self, pods: List[V1Pod], interface: str):
        try:
            for pod in pods:
                self.send_tc_remove_network_corruption(pod, interface)
        except OrchestratorException as e:
            raise OrchestratorException(f'Failed to reset network corruption: {e}')
        
        return True