import unittest
from unittest import mock

import yaml
from kubernetes import client
from requests import PreparedRequest, Session
from requests.adapters import HTTPAdapter, Retry
from requests.structures import CaseInsensitiveDict

from oxn.common.errors import OrchestratorException
from oxn.core.validation import validate_syntax
from oxn.loadgen.locust_kubernetes import LocustKubernetesLoadgenerator
from oxn.models.experiment_spec import ServiceReference
from oxn.models.orchestrator import Orchestrator
from oxn.observability.jaeger import Jaeger
from oxn.observability.prometheus import Prometheus
from oxn.orchestration.cluster_proxy import ClusterProxy, KubeconfigTokenAuth
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator
from oxn.steering.steering_controller import SteeringController
from oxn.tests.unit.spec_mocks import kubernetes_experiment

API_SERVER = "https://192.168.178.80:16443"


def configuration(**attributes) -> client.Configuration:
    config = client.Configuration()
    config.host = API_SERVER
    for name, value in attributes.items():
        setattr(config, name, value)
    return config


def kubernetes_orchestrator() -> KubernetesOrchestrator:
    """A KubernetesOrchestrator for the services of kubernetes_experiment, without a cluster"""
    orchestrator = KubernetesOrchestrator.__new__(KubernetesOrchestrator)
    orchestrator.cluster_proxy = ClusterProxy(configuration())
    orchestrator.experiment_config = validate_syntax(yaml.safe_load(kubernetes_experiment))
    return orchestrator


def pod() -> client.V1Pod:
    return client.V1Pod(
        metadata=client.V1ObjectMeta(name="recommendation-0", namespace="sue"),
        status=client.V1PodStatus(pod_ip="10.1.214.185"),
    )


class ClusterProxyUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proxy = ClusterProxy(configuration())

    def test_it_builds_pod_urls(self):
        self.assertEqual(
            self.proxy.pod_url("sue", "recommendation-0", 5000, "tc"),
            f"{API_SERVER}/api/v1/namespaces/sue/pods/recommendation-0:5000/proxy/tc",
        )

    def test_it_builds_service_urls(self):
        self.assertEqual(
            self.proxy.service_url("sue", "jaeger", 16686, "/jaeger/ui/api/"),
            f"{API_SERVER}/api/v1/namespaces/sue/services/jaeger:16686/proxy/jaeger/ui/api/",
        )


class ClusterProxySessionTests(unittest.TestCase):
    def test_it_uses_the_client_certificate_and_cluster_ca(self):
        config = configuration(cert_file="client.crt", key_file="client.key", ssl_ca_cert="ca.crt")
        session = ClusterProxy(config).session()
        self.assertEqual(session.cert, ("client.crt", "client.key"))
        self.assertEqual(session.verify, "ca.crt")
        self.assertFalse(session.trust_env)

    def test_it_respects_disabled_verification(self):
        session = ClusterProxy(configuration(verify_ssl=False, ssl_ca_cert="ca.crt")).session()
        self.assertFalse(session.verify)

    def test_it_uses_the_kubeconfig_proxy(self):
        session = ClusterProxy(configuration(proxy="http://proxy:3128")).session()
        self.assertEqual(session.proxies, {"https": "http://proxy:3128"})

    def test_it_mounts_retries_for_https(self):
        session = ClusterProxy(configuration()).session(max_retries=Retry(total=7))
        adapter = session.get_adapter(API_SERVER)
        assert isinstance(adapter, HTTPAdapter)
        self.assertEqual(adapter.max_retries.total, 7)

    def test_it_sends_the_current_token_with_each_request(self):
        config = configuration(api_key={"authorization": "Bearer first"})
        auth = KubeconfigTokenAuth(config)
        self.assertEqual(auth(self._request()).headers["Authorization"], "Bearer first")
        config.api_key["authorization"] = "Bearer second"
        self.assertEqual(auth(self._request()).headers["Authorization"], "Bearer second")

    def test_it_sends_no_authorization_header_without_a_token(self):
        self.assertNotIn("Authorization", KubeconfigTokenAuth(configuration())(self._request()).headers)

    @staticmethod
    def _request() -> PreparedRequest:
        request = PreparedRequest()
        request.headers = CaseInsensitiveDict()
        return request


class SteeringControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = SteeringController(mock.Mock(), ClusterProxy(configuration()))

    @mock.patch.object(Session, "post")
    def test_it_posts_through_the_proxy_and_not_to_the_pod_ip(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"status": "ok", "output": ""}
        self.controller.set_network_delay([pod()], "eth0", "90ms", "10ms", "25%")
        self.assertEqual(
            post.call_args.args[0],
            f"{API_SERVER}/api/v1/namespaces/sue/pods/recommendation-0:5000/proxy/tc",
        )
        self.assertEqual(post.call_args.kwargs["json"], {"cmd": "tc qdisc add dev eth0 root netem delay 90ms 10ms 25%"})

    @mock.patch.object(Session, "post")
    def test_it_sends_the_command_of_each_treatment(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"status": "ok"}
        cases = [
            (
                lambda: self.controller.set_network_loss([pod()], "eth0", 5),
                "tc qdisc add dev eth0 root netem loss random 5",
            ),
            (
                lambda: self.controller.set_network_corruption([pod()], "eth0", "5%", "25%"),
                "tc qdisc add dev eth0 root netem corrupt 5% 25%",
            ),
            (lambda: self.controller.remove_netem([pod()], "eth0"), "tc qdisc del dev eth0 root netem"),
        ]
        for call, command in cases:
            with self.subTest(command=command):
                call()
                self.assertEqual(post.call_args.kwargs["json"], {"cmd": command})

    @mock.patch.object(Session, "post")
    def test_it_sets_a_timeout(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"status": "ok"}
        self.controller.remove_netem([pod()], "eth0")
        self.assertIsNotNone(post.call_args.kwargs["timeout"])

    @mock.patch.object(Session, "post")
    def test_it_raises_on_http_errors(self, post):
        post.return_value.status_code = 503
        post.return_value.reason = "Service Unavailable"
        with self.assertRaises(OrchestratorException):
            self.controller.remove_netem([pod()], "eth0")

    @mock.patch.object(Session, "post")
    def test_it_logs_failed_commands(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"status": "error", "message": "exit status 2"}
        with self.assertLogs("oxn.steering.steering_controller", level="ERROR") as logs:
            self.controller.remove_netem([pod()], "eth0")
        self.assertIn("exit status 2", logs.output[0])


class ProxiedClientTests(unittest.TestCase):
    def test_prometheus_goes_through_the_proxy(self):
        prometheus = Prometheus(kubernetes_orchestrator(), target="oxn")
        self.assertEqual(
            prometheus.base_url,
            f"{API_SERVER}/api/v1/namespaces/oxn-external-monitoring/services/kube-prometheus-kube-prome-prometheus:9090"
            "/proxy/api/v1/",
        )
        self.assertIsInstance(prometheus.session.auth, KubeconfigTokenAuth)

    def test_jaeger_goes_through_the_proxy(self):
        jaeger = Jaeger(kubernetes_orchestrator())
        self.assertEqual(
            jaeger.base_url,
            f"{API_SERVER}/api/v1/namespaces/system-under-evaluation/services/jaeger:16686/proxy/jaeger/ui/api/",
        )
        self.assertIsInstance(jaeger.session.auth, KubeconfigTokenAuth)

    def test_internal_urls_use_the_cluster_dns_name(self):
        orchestrator = kubernetes_orchestrator()
        self.assertEqual(
            orchestrator.get_prometheus_url("sue", internal=True), "http://prometheus.system-under-evaluation:9090/"
        )
        self.assertEqual(
            orchestrator.get_prometheus_url("oxn", internal=True),
            "http://kube-prometheus-kube-prome-prometheus.oxn-external-monitoring:9090/",
        )
        self.assertEqual(orchestrator.get_jaeger_url(internal=True), "http://jaeger.system-under-evaluation:16686/")

    def test_grafana_comes_from_the_spec(self):
        orchestrator = kubernetes_orchestrator()
        with self.assertRaises(OrchestratorException) as raised:
            orchestrator.get_grafana_service()
        self.assertIn("services.grafana", str(raised.exception.message))
        services = orchestrator.experiment_config.experiment.services
        assert services is not None
        services.grafana = ServiceReference(name="kube-prometheus-grafana", namespace="oxn-external-monitoring")
        self.assertEqual(orchestrator.get_grafana_service(), services.grafana)

    def test_clients_use_the_urls_and_session_of_any_orchestrator(self):
        orchestrator = mock.Mock(spec=Orchestrator)
        orchestrator.get_prometheus_url.return_value = "http://localhost:9090/"
        orchestrator.get_jaeger_url.return_value = "http://localhost:16686/"
        self.assertEqual(Prometheus(orchestrator, target="sue").base_url, "http://localhost:9090/api/v1/")
        orchestrator.get_prometheus_url.assert_called_once_with("sue")
        self.assertEqual(Jaeger(orchestrator).base_url, "http://localhost:16686/jaeger/ui/api/")
        self.assertIs(Jaeger(orchestrator).session, orchestrator.http_session.return_value)

    @mock.patch.object(Session, "get")
    def test_locust_stats_go_through_the_proxy(self, get):
        get.return_value.json.return_value = {"stats": []}
        generator = LocustKubernetesLoadgenerator.__new__(LocustKubernetesLoadgenerator)
        generator.orchestrator = kubernetes_orchestrator()
        generator.target = mock.Mock(namespace="sue")
        self.assertEqual(generator.get_stats_from_master(), {"stats": []})
        self.assertEqual(
            get.call_args.args[0],
            f"{API_SERVER}/api/v1/namespaces/sue/services/locust-master:8089/proxy/stats/requests",
        )
