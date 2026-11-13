import unittest
import yaml


from oxn.core.validation import validate_syntax
from oxn.models.experiment_spec import ServiceReference
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator
from oxn.tests.unit.spec_mocks import kubernetes_experiment
from oxn.models.orchestrator import Orchestrator


class KubernetesOrchestrationTest(unittest.TestCase):
    spec = kubernetes_experiment
    loaded_spec = yaml.safe_load(spec)

    def setUp(self) -> None:
        self.orc = KubernetesOrchestrator(experiment_config=validate_syntax(self.loaded_spec))

    def tearDown(self) -> None:
        pass

    def test_it_reads_all_pods(self):
        self.assertTrue(self.orc.list_of_all_pods)
        self.assertGreaterEqual(len(self.orc.list_of_all_pods.items), 0)

    def test_it_reads_all_services(self):
        self.assertTrue(self.orc.list_of_all_services)
        self.assertGreaterEqual(len(self.orc.list_of_all_services.items), 0)

    def test_it_initializes_the_client(self):
        self.assertTrue(self.orc.kube_client)

    def test_it_erros_when_not_all_required_found(self):
        self.orc.required_services.append(
            ServiceReference(namespace="monitoring", name="not-running-service")
        )
        with self.assertRaises(Exception):
            self.orc.ready()

    def test_it_checks_all_required(self):
        self.assertTrue(self.orc.ready())
