import unittest
from unittest import mock

from kubernetes import client
from kubernetes.client.exceptions import ApiException
from requests import PreparedRequest, Session
from requests.adapters import Retry

from oxn.loadgen.locust_kubernetes import LocustKubernetesLoadgenerator
from oxn.observability.jaeger import Jaeger
from oxn.observability.prometheus import Prometheus
from oxn.orchestration.cluster_proxy import ClusterProxy, KubeconfigTokenAuth
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator
from oxn.steering.steering_controller import SteeringController

API_SERVER = "https://192.168.178.80:16443"


def configuration(**attributes) -> client.Configuration:
    config = client.Configuration()
    config.host = API_SERVER
    for name, value in attributes.items():
        setattr(config, name, value)
    return config


def kubernetes_orchestrator() -> mock.Mock:
    orchestrator = mock.Mock(spec=KubernetesOrchestrator)
    orchestrator.cluster_proxy = ClusterProxy(configuration())
    orchestrator.get_prometheus_service.return_value = mock.Mock(namespace="monitoring")
    orchestrator.get_prometheus_service.return_value.name = "prometheus"
    orchestrator.get_jaeger_service.return_value = mock.Mock(namespace="sue")
    orchestrator.get_jaeger_service.return_value.name = "jaeger"
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
        self.assertEqual(session.get_adapter(API_SERVER).max_retries.total, 7)

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
        request.headers = {}
        return request


class SteeringControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = SteeringController(mock.Mock(), mock.Mock(), ClusterProxy(configuration()))

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
            (lambda: self.controller.set_network_loss([pod()], "eth0", "5%"), "tc qdisc add dev eth0 root netem loss random 5%"),
            (lambda: self.controller.set_network_corruption([pod()], "eth0", "5%", "25%"), "tc qdisc add dev eth0 root netem corrupt 5% 25%"),
            (lambda: self.controller.remove_network_delay([pod()], "eth0"), "tc qdisc del dev eth0 root netem"),
            (lambda: self.controller.remove_network_loss([pod()], "eth0"), "tc qdisc del dev eth0 root netem"),
            (lambda: self.controller.remove_network_corruption([pod()], "eth0"), "tc qdisc del dev eth0 root netem"),
        ]
        for call, command in cases:
            with self.subTest(command=command):
                call()
                self.assertEqual(post.call_args.kwargs["json"], {"cmd": command})

    @mock.patch.object(Session, "post")
    def test_it_sets_a_timeout(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"status": "ok"}
        self.controller.remove_network_delay([pod()], "eth0")
        self.assertIsNotNone(post.call_args.kwargs["timeout"])

    @mock.patch.object(Session, "post")
    def test_it_raises_on_http_errors(self, post):
        post.return_value.status_code = 503
        post.return_value.reason = "Service Unavailable"
        with self.assertRaises(ApiException):
            self.controller.remove_network_delay([pod()], "eth0")

    @mock.patch.object(Session, "post")
    def test_it_logs_failed_commands(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"status": "error", "message": "exit status 2"}
        with self.assertLogs("oxn.steering.steering_controller", level="ERROR") as logs:
            self.controller.remove_network_delay([pod()], "eth0")
        self.assertIn("exit status 2", logs.output[0])


class ProxiedClientTests(unittest.TestCase):
    def test_prometheus_goes_through_the_proxy(self):
        orchestrator = kubernetes_orchestrator()
        prometheus = Prometheus(orchestrator, target="oxn")
        orchestrator.get_prometheus_service.assert_called_once_with("oxn")
        self.assertEqual(
            prometheus.base_url,
            f"{API_SERVER}/api/v1/namespaces/monitoring/services/prometheus:9090/proxy/api/v1/",
        )

    def test_jaeger_goes_through_the_proxy(self):
        self.assertEqual(
            Jaeger(kubernetes_orchestrator()).base_url,
            f"{API_SERVER}/api/v1/namespaces/sue/services/jaeger:16686/proxy/jaeger/ui/api/",
        )

    def test_other_orchestrators_keep_direct_addresses(self):
        orchestrator = mock.Mock()
        orchestrator.get_prometheus_address.return_value = "localhost"
        orchestrator.get_jaeger_address.return_value = "localhost"
        self.assertEqual(Prometheus(orchestrator).base_url, "http://localhost:9090/api/v1/")
        self.assertEqual(Jaeger(orchestrator).base_url, "http://localhost:16686/jaeger/ui/api/")

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
