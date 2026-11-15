import hashlib
import unittest
from unittest import mock

from oxn.core.runner import ExperimentRunner
from oxn.models.treatment import CompileTimeTreatment, RuntimeTreatment
from oxn.treatments import compile_time as compile_time_package
from oxn.treatments import runtime as runtime_package
from oxn.treatments.registry import TreatmentRegistry


class ExperimentHashTest(unittest.TestCase):
    def _hash(self, config_filename):
        runner = mock.MagicMock(config_filename=config_filename, hash=None)
        ExperimentRunner._compute_hash(runner)
        return runner.hash

    def test_the_hash_identifies_the_spec_path(self):
        self.assertEqual(self._hash("experiments/test.yml"), hashlib.sha256(b"experiments/test.yml").hexdigest())
        self.assertNotEqual(self._hash("experiments/test.yml"), self._hash("experiments/other.yml"))

    def test_without_a_spec_path_there_is_no_short_hash(self):
        with (
            mock.patch("oxn.core.runner.Observer"),
            mock.patch.object(ExperimentRunner, "_build_treatments"),
        ):
            runner = ExperimentRunner(orchestrator=mock.MagicMock(), config=mock.MagicMock())
        self.assertIsNone(runner.short_hash)


class TreatmentKindTest(unittest.TestCase):
    RUNTIME = {"empty", "empty_kubernetes", "delay", "kubernetes_loss", "kubernetes_corrupt", "kubernetes_kill"}
    COMPILE_TIME = {
        "security_context_kubernetes",
        "kubernetes_otel_metrics_interval",
        "kube_probl",
        "scale_deployment",
        "kubernetes_prometheus_interval",
    }

    def test_every_registered_treatment_is_runtime_or_compile_time(self):
        registry = TreatmentRegistry()
        self.assertEqual(set(registry.actions), self.RUNTIME | self.COMPILE_TIME)
        for action in registry.actions:
            treatment_class = registry.treatment_class(action)
            with self.subTest(action=action):
                runtime = action in self.RUNTIME
                base = RuntimeTreatment if runtime else CompileTimeTreatment
                self.assertTrue(issubclass(treatment_class, base))
                self.assertEqual(treatment_class.action, action)
                # is_runtime() only depends on the class, so the instance needs no constructor call
                treatment = treatment_class.__new__(treatment_class)
                self.assertIs(treatment.is_runtime(), runtime)

    def test_each_package_only_holds_its_kind(self):
        for package, base in ((runtime_package, RuntimeTreatment), (compile_time_package, CompileTimeTreatment)):
            for name in package.__all__:
                with self.subTest(treatment=name):
                    self.assertTrue(issubclass(getattr(package, name), base))
