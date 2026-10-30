import os
import unittest
from types import SimpleNamespace
from unittest import mock

import yaml

from oxn.common.errors import OxnException
from oxn.core.runner import ExperimentRunner
from oxn.core.treatments import EmptyTreatment
from oxn.core.validation import SemanticValidator, validate_syntax
from oxn.loadgen.locust_kubernetes import LocustKubernetesLoadgenerator
from oxn.models.experiment_spec import (
    ExperimentSpec,
    HelmRelease,
    Manifests,
    MetricResponseDescription,
    ServiceReference,
    TraceResponseDescription,
)
from oxn.orchestration.docker_orchestration import DockerComposeOrchestrator
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator
from oxn.tests.unit.spec_mocks import experiment_spec_mock, kubernetes_experiment

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
        self.loaded_spec["experiment"]["treatments"][0]["second_name"] = {"action": "pause", "params": {}}
        with self.assertRaises(OxnException):
            validate_syntax(self.loaded_spec)

    def test_syntax_bad_name_inside_of_named_entry(self):
        self.loaded_spec["experiment"]["treatments"][0]["pause_treatment"]["name"] = "other_name"
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
        self.assertEqual(treatment.name, "pause_treatment")
        self.assertEqual(treatment.action, "pause")
        self.assertEqual(treatment.params, {"duration": "30s", "service_name": "frontend"})

    def test_it_applies_defaults_for_optional_sections(self):
        self.loaded_spec["experiment"].pop("treatments")
        experiment = validate_syntax(self.loaded_spec).experiment
        self.assertEqual(experiment.treatments, [])
        self.assertIsNone(experiment.deployment)
        self.assertIsNone(experiment.services)
        self.assertEqual(experiment.sue.required, [])
        self.assertEqual(experiment.loadgen.max_users, 100)
        self.assertEqual(experiment.loadgen.spawn_rate, 10)
        self.assertEqual(experiment.responses[2].limit, 100)


class DeploymentSectionTest(unittest.TestCase):
    def _steps(self, *steps):
        spec = yaml.safe_load(experiment_spec_mock)
        spec["experiment"]["deployment"] = {"steps": list(steps)}
        return validate_syntax(spec).experiment.deployment.steps

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
        self.assertEqual(runner.treatments["empty_treatment"].config["duration"], "1m")

    def test_the_load_generator_reads_its_section(self):
        orchestrator = mock.MagicMock(spec=KubernetesOrchestrator)
        orchestrator.get_address_for_service.return_value = "10.0.0.1"
        spec = kubernetes_spec()
        spec.experiment.loadgen.locust_files[0].path = os.path.join(REPO_ROOT, "locust", "locust_basic_interaction.py")
        generator = LocustKubernetesLoadgenerator(orchestrator=orchestrator, config=spec)
        orchestrator.get_address_for_service.assert_called_with(name="frontend-proxy", namespace="system-under-evaluation")
        self.assertEqual((generator.base_address, generator.port), ("10.0.0.1", 8080))
        self.assertEqual(generator.run_time, 600)
        self.assertEqual((generator.max_users, generator.spawn_rate), (100, 10))
        self.assertIn("UserBehavior", generator._generate_locustfile_content())

    def test_the_kubernetes_orchestrator_finds_services(self):
        with mock.patch("oxn.orchestration.kubernetes_orchestrator.config"), mock.patch(
            "oxn.orchestration.kubernetes_orchestrator.client"
        ), mock.patch("oxn.orchestration.kubernetes_orchestrator.SteeringController"):
            orchestrator = KubernetesOrchestrator(experiment_config=kubernetes_spec())
        with mock.patch.object(orchestrator, "get_address_for_service") as address:
            orchestrator.get_jaeger_address()
            address.assert_called_with(name="jaeger", namespace="system-under-evaluation")
            orchestrator.get_prometheus_address("oxn")
            address.assert_called_with(name="kube-prometheus-kube-prome-prometheus", namespace="oxn-external-monitoring")
        self.assertTrue(orchestrator.ready(expected_services=None))
        orchestrator.kube_client.read_namespaced_service.assert_any_call("grafana", "monitoring")
        self.assertEqual(orchestrator.required_services[1], ServiceReference(namespace="monitoring", name="node-exporter"))

    def test_the_docker_orchestrator_reads_the_sue_section(self):
        # a stand-in, as the class does not implement all abstract methods of Orchestrator and can't be instantiated
        orchestrator = SimpleNamespace(experiment_config=validate_syntax(yaml.safe_load(experiment_spec_mock)))
        DockerComposeOrchestrator._read_orchestration_section(orchestrator)
        self.assertEqual(orchestrator.exclude, ["loadgenerator"])
        self.assertEqual(orchestrator.include, ["otelcol"])
        self.assertTrue(orchestrator.docker_compose_path.endswith("docker-compose.yml"))

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
