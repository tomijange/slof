import copy
import unittest
from unittest import mock

import yaml

from oxn.common.errors import OxnException
from oxn.core.validation import validate_syntax
from oxn.models.treatment import RuntimeTreatment
from oxn.models.treatment_params import DurationParams, TreatmentParams, UncheckedParams
from oxn.tests.unit.spec_mocks import experiment_spec_mock
from oxn.treatments.compile_time.metrics_export_interval import MetricsExportIntervalParams
from oxn.treatments.compile_time.security_context import SecurityContextParams
from oxn.treatments.registry import TreatmentRegistry
from oxn.treatments.runtime import EmptyTreatment
from oxn.treatments.runtime.network_delay import DelayParams

SELECTOR = {"namespace": "system-under-evaluation", "label_selector": "app.kubernetes.io/name", "label": "ad"}
DELAY = {**SELECTOR, "interface": "eth0", "duration": "1m", "delay_time": "45ms"}


class SlowStartParams(DurationParams):
    ramp: int


class SlowStartTreatment(RuntimeTreatment[SlowStartParams]):
    """An extension treatment as a file passed with --extend would define it"""

    action = "slow_start"
    Params = SlowStartParams

    def preconditions(self) -> bool:
        return True

    def inject(self) -> None:
        pass

    def clean(self) -> None:
        pass

    def _validate_orchestrator(self) -> bool:
        return True


class SpecTreatmentValidationTest(unittest.TestCase):
    """Treatment params are checked while the spec is parsed, before anything is deployed"""

    def _spec(self, action, params):
        spec = yaml.safe_load(experiment_spec_mock)
        spec["experiment"]["treatments"] = [{"some_treatment": {"action": action, "params": copy.deepcopy(params)}}]
        return spec

    def _treatment(self, action, params, **kwargs):
        return validate_syntax(self._spec(action, params), **kwargs).experiment.treatments[0]

    def _error(self, action, params, **kwargs) -> str:
        with self.assertRaises(OxnException) as raised:
            self._treatment(action, params, **kwargs)
        return str(raised.exception)

    def test_it_builds_the_params_model_of_the_action(self):
        params = self._treatment("delay", DELAY).params
        assert isinstance(params, DelayParams)
        self.assertEqual((params.delay_jitter, params.delay_correlation), ("0ms", "0%"))
        self.assertEqual(params.duration_seconds, 60)

    def test_it_rejects_unknown_actions(self):
        error = self._error("dleay", DELAY)
        self.assertIn("Unknown action dleay", error)
        self.assertIn("delay", error)

    def test_it_names_missing_params(self):
        error = self._error("delay", {"duration": "1m"})
        self.assertIn("experiment.treatments.0.params", error)
        for missing in ("namespace", "label_selector", "label", "interface", "delay_time"):
            self.assertIn(f"{missing}: Field required", error)

    def test_it_rejects_unknown_params(self):
        self.assertIn("delay_distribution", self._error("delay", {**DELAY, "delay_distribution": "pareto"}))

    def test_it_checks_values(self):
        for action, params, field in (
            ("delay", {**DELAY, "delay_time": "45"}, "delay_time"),
            ("delay", {**DELAY, "duration": "1m30x"}, "duration"),
            ("delay", {**DELAY, "delay_correlation": "120%"}, "delay_correlation"),
            ("kubernetes_loss", {**DELAY, "loss_percentage": 101}, "loss_percentage"),
            ("kubernetes_kill", {**SELECTOR, "amount_to_kill": 0}, "amount_to_kill"),
            ("kube_probl", {"sampling_percentage": 5}, "hash_seed"),
            (
                "kubernetes_prometheus_interval",
                {"interval": "", "evaluation_interval": "5s", "scrape_timeout": "3s"},
                "interval",
            ),
            ("security_context_kubernetes", {**SELECTOR, "capabilities": {"add": []}}, "capabilities.add"),
            ("deployment_image", {**SELECTOR, "image": ""}, "image"),
        ):
            with self.subTest(action=action, field=field):
                self.assertIn(f"{field}:", self._error(action, params))

    def test_it_accepts_the_params_of_every_shipped_treatment(self):
        loss = {k: v for k, v in DELAY.items() if k != "delay_time"}
        for action, params in (
            ("empty", {"duration": "30s"}),
            ("empty_kubernetes", {"duration": "1m30s"}),
            ("kubernetes_loss", {**loss, "loss_percentage": 15}),
            ("kubernetes_corrupt", {**loss, "corrupt_percentage": "10%"}),
            ("kubernetes_kill", {**SELECTOR, "amount_to_kill": 1}),
            ("scale_deployment", {**SELECTOR, "scale_to": 0}),
            ("deployment_image", {**SELECTOR, "image": "ghcr.io/open-telemetry/demo:2.0.2-ad"}),
            ("deployment_image", {**SELECTOR, "image": "busybox", "container": "ad"}),
            ("kube_probl", {"sampling_percentage": 5.0, "hash_seed": 22}),
            ("kubernetes_otel_metrics_interval", {**SELECTOR, "interval": "15s"}),
            ("kubernetes_prometheus_interval", {"interval": "5s", "evaluation_interval": "5s", "scrape_timeout": "3s"}),
            ("security_context_kubernetes", {**SELECTOR, "capabilities": {"add": ["NET_ADMIN"]}}),
        ):
            with self.subTest(action=action):
                self.assertIsInstance(self._treatment(action, params).params, TreatmentParams)

    def test_derived_values_are_properties(self):
        params = self._treatment("kubernetes_otel_metrics_interval", {**SELECTOR, "interval": "1s"}).params
        assert isinstance(params, MetricsExportIntervalParams)
        self.assertEqual(params.interval_ms, 1000)

    def test_extension_treatments_are_checked_with_their_own_model(self):
        registry = TreatmentRegistry([SlowStartTreatment])
        params = self._treatment("slow_start", {"duration": "1m", "ramp": 3}, treatments=registry).params
        self.assertEqual(params, SlowStartParams(duration="1m", ramp=3))
        self.assertIn("ramp", self._error("slow_start", {"duration": "1m"}, treatments=registry))
        self.assertIn("Unknown action slow_start", self._error("slow_start", {"duration": "1m"}))

    def test_without_checks_params_are_kept_as_they_are(self):
        params = self._treatment("slow_start", {"anything": [1, 2]}, check_treatments=False).params
        self.assertIsInstance(params, UncheckedParams)
        self.assertEqual(params.model_dump(), {"anything": [1, 2]})

    def test_dumping_the_spec_keeps_the_params(self):
        spec = validate_syntax(self._spec("delay", DELAY))
        self.assertEqual(spec.model_dump()["experiment"]["treatments"][0]["params"]["delay_time"], "45ms")


class TreatmentRegistryTest(unittest.TestCase):
    def test_extensions_replace_built_in_actions(self):
        class OwnEmpty(SlowStartTreatment):
            action = "empty"

        self.assertIs(TreatmentRegistry([OwnEmpty]).treatment_class("empty"), OwnEmpty)
        self.assertIs(TreatmentRegistry().treatment_class("empty"), EmptyTreatment)

    def test_it_rejects_treatments_without_action_or_params(self):
        no_action = type("NoAction", (SlowStartTreatment,), {"action": None})
        no_params = type("NoParams", (SlowStartTreatment,), {"Params": dict})
        for treatment_class in (no_action, no_params):
            with self.subTest(treatment=treatment_class.__name__), self.assertRaises(OxnException):
                TreatmentRegistry([treatment_class])

    def test_treatments_built_from_mappings_validate_them(self):
        treatment = EmptyTreatment(params={"duration": "2m"}, name="wait", orchestrator=mock.MagicMock())
        self.assertEqual(treatment.params.duration_seconds, 120)
        with self.assertRaises(OxnException):
            EmptyTreatment(params={"duration": "2 minutes"}, name="wait", orchestrator=mock.MagicMock())

    def test_security_context_capabilities_are_passed_as_a_mapping(self):
        params = SecurityContextParams.model_validate({**SELECTOR, "capabilities": {"add": ["NET_ADMIN"]}})
        self.assertEqual(params.capabilities.model_dump(), {"add": ["NET_ADMIN"], "drop": []})
