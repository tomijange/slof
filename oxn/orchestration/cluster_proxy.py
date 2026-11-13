"""
Purpose: Reaches HTTP endpoints inside the cluster through the proxy of the Kubernetes API server.
Functionality: Builds proxy urls for pods and services and creates requests sessions that authenticate with the
    credentials from the kubeconfig. oxn therefore works wherever kubectl works, without a route to pod and cluster IPs.
Connection: Created by the KubernetesOrchestrator and used by the SteeringController, Prometheus, Jaeger and the
    LocustKubernetesLoadgenerator. Do not send load generator traffic through it, as the API server would become
    part of the measured path.
"""
from typing import Optional

import requests
from kubernetes import client
from requests.adapters import HTTPAdapter, Retry
from requests.auth import AuthBase


class KubeconfigTokenAuth(AuthBase):
    """Adds the current token to each request, because tokens from exec plugins can expire during a run"""

    def __init__(self, configuration: client.Configuration):
        self.configuration = configuration

    def __call__(self, request):
        token = self.configuration.get_api_key_with_prefix("authorization")
        if token:
            request.headers["Authorization"] = token
        return request


class ClusterProxy:
    """HTTP access to pods and services through the API server. Expects the kubeconfig to be loaded already."""

    def __init__(self, configuration: Optional[client.Configuration] = None):
        self.configuration = configuration or client.Configuration.get_default_copy()

    def pod_url(self, namespace: str, pod: str, port: int, path: str = "") -> str:
        """Build the url of a path on one specific pod"""
        return self._proxy_url(namespace, "pods", pod, port, path)

    def service_url(self, namespace: str, service: str, port: int, path: str = "") -> str:
        """Build the url of a path on a service. The API server picks one of its pods, also for headless services."""
        return self._proxy_url(namespace, "services", service, port, path)

    def session(self, max_retries: Optional[Retry] = None) -> requests.Session:
        """Create a session for the urls of this proxy"""
        configuration = self.configuration
        session = requests.Session()
        # the environment (netrc, REQUESTS_CA_BUNDLE) would otherwise take precedence over the settings below
        session.trust_env = False
        session.auth = KubeconfigTokenAuth(configuration)
        session.verify = (configuration.ssl_ca_cert or True) if configuration.verify_ssl else False
        if configuration.cert_file:
            session.cert = (configuration.cert_file, configuration.key_file)
        if configuration.proxy:
            session.proxies = {"https": configuration.proxy}
        if max_retries is not None:
            session.mount("https://", HTTPAdapter(max_retries=max_retries))
        return session

    def _proxy_url(self, namespace: str, resource: str, name: str, port: int, path: str) -> str:
        return f"{self.configuration.host}/api/v1/namespaces/{namespace}/{resource}/{name}:{port}/proxy/{path.lstrip('/')}"
