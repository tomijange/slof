import importlib.util
import os
import unittest
from unittest import mock

import yaml

from locust import HttpUser
from oxn.common.errors import LocustException, OxnException
from oxn.common.settings import LOCUST_IMAGE
from oxn.core.runner import ExperimentRunner
from oxn.core.validation import SemanticValidator, load_variants, validate_syntax
from oxn.loadgen.locust_kubernetes import METRICS_FILE, LocustKubernetesLoadgenerator
from oxn.models.experiment_spec import (
    ExperimentSpec,
    HelmRelease,
    Manifests,
    MetricResponseDescription,
    ServiceReference,
    TraceResponseDescription,
)
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator
from oxn.tests.unit.spec_mocks import experiment_spec_mock, kubernetes_experiment
from oxn.treatments.runtime import EmptyTreatment
from oxn.treatments.runtime.empty import EmptyParams

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def kubernetes_spec() -> ExperimentSpec:
    return validate_syntax(yaml.safe_load(kubernetes_experiment))


class SpecificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.loaded_spec = yaml.safe_load(experiment_spec_mock)

    def test_syntax_ok(self):
        self.assertIsInstance(validate_syntax(self.loaded_spec), ExperimentSpec)

    def test_syntax_bad_no_responses(self):
        self.loaded_spec["experiment"].pop("responses")
        with self.assertRaises(OxnException):
            validate_syntax(self.loaded_spec)

    def test_syntax_bad_unknown_key(self):
        self.loaded_spec["experiment"]["randomize"] = 42
        with self.assertRaises(OxnException):
            validate_syntax(self.loaded_spec)

    def test_syntax_bad_incorrect_type_loadgen_run_time(self):
        self.loaded_spec["experiment"]["loadgen"]["run_time"] = 42.0
        with self.assertRaises(OxnException):
            validate_syntax(self.loaded_spec)

    def test_syntax_bad_unknown_orchestrator(self):
        self.loaded_spec["experiment"]["orchestrator"] = "nomad"
        with self.assertRaises(OxnException):
            validate_syntax(self.loaded_spec)

    def test_syntax_bad_unknown_response_type(self):
        self.loaded_spec["experiment"]["responses"][0]["my_metric_response_no_params"]["type"] = "log"
        with self.assertRaises(OxnException):
            validate_syntax(self.loaded_spec)

    def test_syntax_bad_entry_with_two_names(self):
        self.loaded_spec["experiment"]["treatments"][0]["second_name"] = {"action": "empty", "params": {}}
        with self.assertRaises(OxnException):
            validate_syntax(self.loaded_spec)

    def test_syntax_bad_name_inside_of_named_entry(self):
        self.loaded_spec["experiment"]["treatments"][0]["empty_treatment"]["name"] = "other_name"
        with self.assertRaises(OxnException):
            validate_syntax(self.loaded_spec)

    def test_syntax_bad_locust_file_without_path(self):
        self.loaded_spec["experiment"]["loadgen"]["locust_files"] = ["locust/locust_basic_interaction.py"]
        with self.assertRaises(OxnException):
            validate_syntax(self.loaded_spec)

    def test_it_reports_where_validation_failed(self):
        self.loaded_spec["experiment"]["loadgen"]["run_time"] = 42.0
        with self.assertRaises(OxnException) as raised:
            validate_syntax(self.loaded_spec)
        self.assertIn("experiment.loadgen.run_time", str(raised.exception))

    def test_it_names_responses_and_picks_their_type(self):
        responses = validate_syntax(self.loaded_spec).experiment.responses
        self.assertEqual(
            [(response.name, type(response)) for response in responses],
            [
                ("my_metric_response_no_params", MetricResponseDescription),
                ("otelcol_spans", MetricResponseDescription),
                ("my_trace_response", TraceResponseDescription),
            ],
        )

    def test_it_names_treatments(self):
        treatment = validate_syntax(self.loaded_spec).experiment.treatments[0]
        self.assertEqual(treatment.name, "empty_treatment")
        self.assertEqual(treatment.action, "empty")
        self.assertEqual(treatment.params, EmptyParams(duration="30s"))

    def test_it_applies_defaults_for_optional_sections(self):
        self.loaded_spec["experiment"].pop("treatments")
        experiment = validate_syntax(self.loaded_spec).experiment
        self.assertEqual(experiment.treatments, [])
        self.assertIsNone(experiment.deployment)
        self.assertIsNone(experiment.services)
        self.assertEqual(experiment.sue.required, [])
        self.assertEqual(experiment.loadgen.max_users, 100)
        self.assertEqual(experiment.loadgen.spawn_rate, 10)
        trace_response = experiment.responses[2]
        assert isinstance(trace_response, TraceResponseDescription)
        self.assertEqual(trace_response.limit, 100)


class DeploymentSectionTest(unittest.TestCase):
    def _steps(self, *steps):
        spec = yaml.safe_load(experiment_spec_mock)
        spec["experiment"]["deployment"] = {"steps": list(steps)}
        deployment = validate_syntax(spec).experiment.deployment
        assert deployment is not None
        return deployment.steps

    def test_it_builds_typed_steps_in_order(self):
        helm = {"release": "shop", "chart": "demo", "namespace": "sue", "set": {"a.b": True}}
        steps = self._steps({"helm": helm}, {"manifests": {"paths": ["k8s/elasticsearch/"]}})
        self.assertIsInstance(steps[0], HelmRelease)
        self.assertEqual(steps[0].set, {"a.b": True})
        self.assertIsInstance(steps[1], Manifests)
        self.assertEqual(steps[1].paths, ["k8s/elasticsearch/"])

    def test_it_rejects_unknown_step_kinds(self):
        with self.assertRaises(OxnException):
            self._steps({"kustomize": {"paths": ["k8s/"]}})

    def test_it_rejects_steps_with_the_fields_of_another_kind(self):
        with self.assertRaises(OxnException):
            self._steps({"helm": {"paths": ["k8s/"]}})

    def test_it_does_not_accept_the_kind_as_a_field(self):
        with self.assertRaises(OxnException):
            self._steps({"helm": {"kind": "manifests", "paths": ["k8s/"]}})


class SpecConsumersTest(unittest.TestCase):
    """The components that read the spec work on the model"""

    def test_the_runner_builds_treatments(self):
        runner = ExperimentRunner(orchestrator=mock.MagicMock(), config=kubernetes_spec())
        self.assertIsInstance(runner.treatments["empty_treatment"], EmptyTreatment)
        self.assertEqual(runner.treatments["empty_treatment"].params.duration_seconds, 60)

    def test_the_load_generator_reads_its_section(self):
        orchestrator = mock.MagicMock(spec=KubernetesOrchestrator)
        orchestrator.get_address_for_service.return_value = "10.0.0.1"
        spec = kubernetes_spec()
        spec.experiment.loadgen.locust_files[0].path = os.path.join(REPO_ROOT, "locust", "locust_basic_interaction.py")
        generator = LocustKubernetesLoadgenerator(orchestrator=orchestrator, config=spec)
        orchestrator.get_address_for_service.assert_called_with(
            name="frontend-proxy", namespace="system-under-evaluation"
        )
        self.assertEqual((generator.base_address, generator.port), ("10.0.0.1", 8080))
        self.assertEqual(generator.run_time, 600)
        self.assertEqual((generator.max_users, generator.spawn_rate), (100, 10))
        self.assertIn("UserBehavior", generator._shipped_files()["locust_basic_interaction.py"])

    def test_the_kubernetes_orchestrator_finds_services(self):
        with (
            mock.patch("oxn.orchestration.kubernetes_orchestrator.config"),
            mock.patch("oxn.orchestration.kubernetes_orchestrator.client"),
            mock.patch("oxn.orchestration.kubernetes_orchestrator.SteeringController"),
        ):
            orchestrator = KubernetesOrchestrator(experiment_config=kubernetes_spec())
        self.assertEqual(orchestrator.get_jaeger_url(internal=True), "http://jaeger.system-under-evaluation:16686/")
        self.assertEqual(
            orchestrator.get_prometheus_url("oxn", internal=True),
            "http://kube-prometheus-kube-prome-prometheus.oxn-external-monitoring:9090/",
        )
        self.assertTrue(orchestrator.ready(expected_services=None))
        read_service = orchestrator.kube_client.read_namespaced_service
        assert isinstance(read_service, mock.Mock)
        read_service.assert_any_call("grafana", "monitoring")
        self.assertEqual(
            orchestrator.required_services[1], ServiceReference(namespace="monitoring", name="node-exporter")
        )

    def test_the_semantic_validator_reports_unknown_names(self):
        validator = SemanticValidator.__new__(SemanticValidator)
        validator.experiment_spec = validate_syntax(yaml.safe_load(experiment_spec_mock))
        validator.messages = []
        validator.metric_names = {"prometheus_metric"}
        validator.label_names = set()
        validator.label_values = {}
        validator.service_names = set()
        validator.validate_responses()
        self.assertEqual(
            validator.messages,
            [
                "Prometheus does not recognize metric name otelcol_exporter_sent_spans",
                "Prometheus does not recognize label name exporter",
                "Prometheus does not recognize label value logging for label exporter",
                "Jaeger does not know service name my_trace_response",
            ],
        )


class LocustManifestTest(unittest.TestCase):
    """The manifests of the in-cluster Locust, rendered from oxn/loadgen/kubernetes/ for the locust files of test.yml"""

    LABELS = {"release": "kube-prometheus"}

    def setUp(self):
        (variant,) = load_variants(os.path.join(REPO_ROOT, "experiments", "test.yml"))
        self.orchestrator = mock.MagicMock(spec=KubernetesOrchestrator)
        self.orchestrator.get_address_for_service.return_value = "10.0.0.1"
        self.orchestrator.get_service_monitor_labels.return_value = self.LABELS
        self.generator = LocustKubernetesLoadgenerator(orchestrator=self.orchestrator, config=variant.spec)
        rendered = self.generator._generate_k8s_yaml(service_monitor_labels=self.LABELS)
        self.manifests = {name: yaml.safe_load(text) for name, text in rendered.items()}

    def test_every_resource_is_in_the_namespace_of_the_load_generator(self):
        self.assertEqual(self.generator.namespace, "oxn-loadgen")
        for name, manifest in self.manifests.items():
            with self.subTest(name=name):
                self.assertEqual(manifest["metadata"]["namespace"], "oxn-loadgen")

    def test_the_configmap_holds_every_locust_file_data_file_and_the_metrics_module(self):
        data = self.manifests["configmap"]["data"]
        self.assertEqual(
            set(data), {"locust_basic_interaction.py", "locust_otel_demo.py", "people.json", "oxn_metrics.py"}
        )
        with open(os.path.join(REPO_ROOT, "locust", "locust_otel_demo.py")) as fp:
            self.assertEqual(data["locust_otel_demo.py"], fp.read())

    def test_master_and_workers_run_every_locust_file_in_the_pinned_image(self):
        paths = "/home/locust/locust_basic_interaction.py,/home/locust/locust_otel_demo.py,/home/locust/oxn_metrics.py"
        for name in ("master", "worker"):
            (container,) = self.manifests[name]["spec"]["template"]["spec"]["containers"]
            args = container["args"]
            with self.subTest(name=name):
                self.assertEqual(args[args.index("-f") + 1], paths)
                self.assertEqual(container["volumeMounts"][0]["mountPath"], "/home/locust")
                self.assertEqual(container["image"], LOCUST_IMAGE)
                self.assertNotIn("imagePullPolicy", container)

    def test_the_image_is_the_locust_version_oxn_pins(self):
        with open(os.path.join(REPO_ROOT, "requirements.txt")) as fp:
            pinned = [line.strip().split("==")[1] for line in fp if line.startswith("locust==")]
        self.assertEqual(LOCUST_IMAGE, f"locustio/locust:{pinned[0]}")

    def test_the_service_monitor_selects_the_master_with_the_labels_of_prometheus(self):
        monitor = self.manifests["servicemonitor"]
        self.assertEqual(monitor["metadata"]["labels"], self.LABELS)
        selected = monitor["spec"]["selector"]["matchLabels"]
        self.assertLessEqual(selected.items(), self.manifests["service"]["metadata"]["labels"].items())
        self.assertEqual(monitor["spec"]["endpoints"][0]["path"], "/metrics")
        ports = [port["name"] for port in self.manifests["service"]["spec"]["ports"]]
        self.assertIn(monitor["spec"]["endpoints"][0]["port"], ports)

    def test_start_applies_everything_in_its_namespace_and_kill_removes_it(self):
        self.generator.start()
        self.orchestrator.get_service_monitor_labels.assert_called_once_with("oxn")
        self.orchestrator.ensure_namespace.assert_called_once_with("oxn-loadgen")
        applied = [yaml.safe_load(c.args[0])["kind"] for c in self.orchestrator.deploy_yaml.call_args_list]
        self.assertEqual(applied, ["ConfigMap", "Deployment", "Deployment", "Service", "ServiceMonitor"])
        self.orchestrator.delete_yaml.side_effect = [OxnException(message="gone"), None, None, None, None]
        with self.assertLogs("oxn.loadgen.locust_kubernetes", "WARNING"):
            self.generator.kill()
        removed = [yaml.safe_load(c.args[0])["kind"] for c in self.orchestrator.delete_yaml.call_args_list]
        self.assertEqual(removed, ["ServiceMonitor", "Service", "Deployment", "Deployment", "ConfigMap"])
        self.generator.kill()
        self.assertEqual(self.orchestrator.delete_yaml.call_count, 5)

    def test_without_a_prometheus_operator_there_is_no_service_monitor(self):
        self.orchestrator.get_service_monitor_labels.return_value = None
        with self.assertLogs("oxn.loadgen.locust_kubernetes", "WARNING"):
            self.generator.start()
        applied = [yaml.safe_load(c.args[0])["kind"] for c in self.orchestrator.deploy_yaml.call_args_list]
        self.assertNotIn("ServiceMonitor", applied)

    def test_files_with_the_same_name_are_rejected(self):
        # the clash is found before the second file is read, so it need not exist
        self.generator.data_files = [
            os.path.join(REPO_ROOT, "locust", "people.json"),
            os.path.join(REPO_ROOT, "elsewhere", "people.json"),
        ]
        with self.assertRaises(LocustException):
            self.generator._shipped_files()

    def test_the_user_classes_of_the_shipped_files_have_distinct_names(self):
        # locust stops with "Duplicate user class names" otherwise
        names = []
        for locust_file in self.generator.locust_files or []:
            module = self.generator._load_locust_file(locust_file.path)
            names += [
                n
                for n, c in vars(module).items()
                if isinstance(c, type) and issubclass(c, HttpUser) and c is not HttpUser
            ]
        self.assertEqual(sorted(names), ["BasicInteractionUser", "OtelDemoUser"])


class LocustMetricsTest(unittest.TestCase):
    """oxn_metrics.py, which the master of the in-cluster Locust serves at /metrics"""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("oxn_metrics", METRICS_FILE)
        assert spec is not None and spec.loader is not None
        self.metrics = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.metrics)

    def test_the_histogram_counts_requests_up_to_each_edge(self):
        entry = mock.Mock(num_requests=4, num_failures=1, total_response_time=1270.0)
        entry.name, entry.method = '/api/"cart"', "GET"
        entry.response_times = {20: 1, 100: 1, 150: 1, 1000: 1}
        environment = mock.Mock()
        environment.runner.stats.entries = {("/api/cart", "GET"): entry}
        environment.runner.user_count = 7
        text = self.metrics.render(environment)
        labels = 'name="/api/\\"cart\\"",method="GET"'
        for line in (
            f"locust_requests_total{{{labels}}} 4",
            f"locust_request_failures_total{{{labels}}} 1",
            f'locust_request_duration_seconds_bucket{{{labels},le="0.01"}} 0',
            f'locust_request_duration_seconds_bucket{{{labels},le="0.1"}} 2',
            f'locust_request_duration_seconds_bucket{{{labels},le="1.0"}} 4',
            f'locust_request_duration_seconds_bucket{{{labels},le="+Inf"}} 4',
            f"locust_request_duration_seconds_sum{{{labels}}} 1.27",
            f"locust_request_duration_seconds_count{{{labels}}} 4",
            "locust_users 7",
        ):
            self.assertIn(line + "\n", text)
