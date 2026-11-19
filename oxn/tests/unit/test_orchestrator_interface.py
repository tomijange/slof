import unittest
from typing import List
from unittest import mock

import yaml
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from oxn.common.errors import OrchestratorException, OxnException
from oxn.core.validation import validate_syntax
from oxn.models.orchestrator import Orchestrator
from oxn.models.workload import WorkloadInstance, WorkloadSelector
from oxn.orchestration.kubernetes_orchestrator import PROMETHEUS, KubernetesOrchestrator
from oxn.steering.steering_controller import SIDECAR_CONTAINER_NAME, SteeringController
from oxn.tests.unit.spec_mocks import kubernetes_experiment
from oxn.treatments.registry import TreatmentRegistry
from oxn.treatments.runtime import EmptyKubernetesTreatment, KillTreatment, NetworkDelayTreatment

SELECTOR = {"namespace": "sue", "label_selector": "app.kubernetes.io/name", "label": "ad"}
WORKLOAD = WorkloadSelector(namespace="sue", label_selector="app.kubernetes.io/name", label="ad")
KUBERNETES_ONLY = {"empty_kubernetes", "security_context_kubernetes"}


def generic_orchestrator() -> mock.Mock:
    """An orchestrator that only has the methods of the interface, as a Docker Compose one would"""
    return mock.Mock(spec=Orchestrator)


def deployment(*containers: str) -> client.V1Deployment:
    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name="ad", namespace="sue"),
        spec=client.V1DeploymentSpec(
            selector=client.V1LabelSelector(match_labels={"app.kubernetes.io/name": "ad"}),
            template=client.V1PodTemplateSpec(
                spec=client.V1PodSpec(containers=[client.V1Container(name=name) for name in containers])
            ),
        ),
    )


def containers(found: client.V1Deployment) -> List[client.V1Container]:
    assert found.spec is not None
    assert found.spec.template.spec is not None
    return found.spec.template.spec.containers


class TreatmentOrchestratorTest(unittest.TestCase):
    def test_only_kubernetes_treatments_reject_other_orchestrators(self):
        registry = TreatmentRegistry()
        for action in registry.actions:
            treatment_class = registry.treatment_class(action)
            treatment = treatment_class.__new__(treatment_class)
            treatment.name = action
            treatment.messages = []
            with self.subTest(action=action):
                treatment.orchestrator = generic_orchestrator()
                self.assertIs(treatment._validate_orchestrator(), action not in KUBERNETES_ONLY)
                treatment.orchestrator = mock.Mock(spec=KubernetesOrchestrator)
                self.assertTrue(treatment._validate_orchestrator())

    def test_building_a_kubernetes_treatment_for_another_orchestrator_fails(self):
        with self.assertRaises(OxnException) as raised:
            EmptyKubernetesTreatment(params={"duration": "1s"}, name="wait", orchestrator=generic_orchestrator())
        self.assertIn("only supported for Kubernetes", str(raised.exception.explanation))

    @mock.patch("oxn.treatments.runtime.netem.time.sleep")
    def test_network_treatments_use_the_interface(self, sleep):
        orchestrator = generic_orchestrator()
        params = {**SELECTOR, "interface": "eth0", "duration": "5s", "delay_time": "90ms"}
        treatment = NetworkDelayTreatment(params=params, name="delay", orchestrator=orchestrator)

        self.assertTrue(treatment.preconditions())
        treatment.inject()
        treatment.clean()

        orchestrator.prepare_network_faults.assert_called_once_with(WORKLOAD)
        orchestrator.set_network_delay.assert_called_once_with(
            WORKLOAD, interface="eth0", delay_time="90ms", jitter="0ms", correlation="0%"
        )
        orchestrator.remove_network_faults.assert_called_once_with(WORKLOAD, "eth0")
        sleep.assert_called_once_with(5)

    def test_kill_needs_enough_running_instances(self):
        orchestrator = generic_orchestrator()
        orchestrator.get_instances.return_value = [
            WorkloadInstance(name="ad-0", namespace="sue", state="Running", running=True),
            WorkloadInstance(name="ad-1", namespace="sue", state="Pending", running=False),
        ]
        for amount, expected in ((3, "higher than the amount"), (2, "ad-1")):
            treatment = KillTreatment(
                params={**SELECTOR, "amount_to_kill": amount}, name="k", orchestrator=orchestrator
            )
            with self.subTest(amount=amount):
                self.assertFalse(treatment.preconditions())
                self.assertIn(expected, treatment.messages[0])

        orchestrator.get_instances.return_value = orchestrator.get_instances.return_value[:1]
        treatment = KillTreatment(params={**SELECTOR, "amount_to_kill": 1}, name="k", orchestrator=orchestrator)
        self.assertTrue(treatment.preconditions())
        treatment.inject()
        orchestrator.kill_instance.assert_called_once_with(orchestrator.get_instances.return_value[0])


class KubernetesOrchestratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = KubernetesOrchestrator.__new__(KubernetesOrchestrator)
        self.apps = mock.Mock()
        self.core = mock.Mock()
        self.custom = mock.Mock()
        self.orchestrator.api_client = self.apps
        self.orchestrator.kube_client = self.core
        self.orchestrator.custom_client = self.custom
        self.orchestrator.steering_controller = SteeringController(self.apps, mock.MagicMock())

    def _deployment(self, *containers: str) -> client.V1Deployment:
        found = deployment(*containers)
        self.apps.list_namespaced_deployment.return_value = client.V1DeploymentList(items=[found])
        return found

    @mock.patch.object(KubernetesOrchestrator, "_wait_until_deployment_ready")
    def test_the_sidecar_is_added_once(self, wait):
        found = self._deployment("ad")
        self.orchestrator.prepare_network_faults(WORKLOAD)
        self.assertEqual([c.name for c in containers(found)], ["ad", SIDECAR_CONTAINER_NAME])
        wait.assert_called_once()

        self._deployment("ad", SIDECAR_CONTAINER_NAME)
        self.orchestrator.prepare_network_faults(WORKLOAD)
        self.assertEqual(self.apps.patch_namespaced_deployment.call_count, 1)
        wait.assert_called_once()

    def test_pods_are_instances(self):
        self.core.list_namespaced_pod.return_value = client.V1PodList(
            items=[
                client.V1Pod(
                    metadata=client.V1ObjectMeta(name="ad-0", namespace="sue"),
                    status=client.V1PodStatus(phase="Running"),
                )
            ]
        )
        self.assertEqual(
            self.orchestrator.get_instances(WORKLOAD),
            [WorkloadInstance(name="ad-0", namespace="sue", state="Running", running=True)],
        )
        self.core.list_namespaced_pod.assert_called_once_with("sue", label_selector="app.kubernetes.io/name=ad")

    def test_environment_variables_are_read_from_the_main_container(self):
        found = self._deployment("ad", SIDECAR_CONTAINER_NAME)
        containers(found)[0].env = [client.V1EnvVar(name="OTEL_METRIC_EXPORT_INTERVAL", value="5000")]
        self.assertEqual(self.orchestrator.get_environment_variable(WORKLOAD, "OTEL_METRIC_EXPORT_INTERVAL"), "5000")
        self.assertIsNone(self.orchestrator.get_environment_variable(WORKLOAD, "OTHER"))

        self.orchestrator.set_environment_variable(WORKLOAD, "OTEL_METRIC_EXPORT_INTERVAL", "1000")
        patched = self.apps.patch_namespaced_deployment.call_args.kwargs["body"]
        self.assertEqual(patched.spec.template.spec.containers[0].env[0].value, "1000")

    def test_manifests_are_deployed_by_kind_and_replaced_if_they_exist(self):
        manifest = "kind: Service\nmetadata: {name: locust-master, namespace: sue}\n"
        self.core.create_namespaced_service.side_effect = [ApiException(reason="already exists"), "created"]
        self.assertEqual(self.orchestrator.deploy_yaml(manifest), "created")
        self.core.delete_namespaced_service.assert_called_once_with(name="locust-master", namespace="sue")
        self.orchestrator.delete_yaml(manifest.replace("Service", "ConfigMap"))
        self.core.delete_namespaced_config_map.assert_called_once_with(name="locust-master", namespace="sue")
        with self.assertRaises(OrchestratorException):
            self.orchestrator.deploy_yaml(manifest.replace("Service", "Secret"))

    def test_service_monitors_are_custom_objects(self):
        manifest = "kind: ServiceMonitor\nmetadata: {name: locust-master, namespace: oxn-loadgen}\n"
        self.orchestrator.deploy_yaml(manifest)
        kwargs = self.custom.create_namespaced_custom_object.call_args.kwargs
        self.assertEqual(
            (kwargs["group"], kwargs["version"], kwargs["plural"], kwargs["namespace"]),
            ("monitoring.coreos.com", "v1", "servicemonitors", "oxn-loadgen"),
        )
        self.orchestrator.delete_yaml(manifest)
        self.assertEqual(self.custom.delete_namespaced_custom_object.call_args.kwargs["name"], "locust-master")

    def test_service_monitor_labels_come_from_the_prometheus_of_the_target(self):
        self.orchestrator.experiment_config = validate_syntax(yaml.safe_load(kubernetes_experiment))
        self.core.read_namespaced_service.return_value = client.V1Service(
            spec=client.V1ServiceSpec(selector={"operator.prometheus.io/name": "main"})
        )
        self.custom.get_namespaced_custom_object.return_value = {
            "spec": {"serviceMonitorSelector": {"matchLabels": {"release": "kube-prometheus"}}}
        }
        self.assertEqual(self.orchestrator.get_service_monitor_labels("oxn"), {"release": "kube-prometheus"})
        self.core.read_namespaced_service.assert_called_with(
            "kube-prometheus-kube-prome-prometheus", "oxn-external-monitoring"
        )
        self.assertEqual(self.custom.get_namespaced_custom_object.call_args.args[-1], "main")
        # a Prometheus without the operator
        self.core.read_namespaced_service.return_value = client.V1Service(spec=client.V1ServiceSpec(selector={}))
        self.assertIsNone(self.orchestrator.get_service_monitor_labels("oxn"))

    def test_a_missing_namespace_is_created_and_an_existing_one_left_alone(self):
        self.orchestrator.ensure_namespace("oxn-loadgen")
        self.core.create_namespace.assert_not_called()
        self.core.read_namespace.side_effect = ApiException(status=404)
        self.orchestrator.ensure_namespace("oxn-loadgen")
        self.assertEqual(self.core.create_namespace.call_args.args[0].metadata.name, "oxn-loadgen")

    @mock.patch.object(KubernetesOrchestrator, "restart")
    def test_scrape_values_are_written_to_the_configmap(self, restart):
        prometheus_config = {
            "global": {"scrape_interval": "15s", "evaluation_interval": "15s", "scrape_timeout": "10s"}
        }
        self.core.read_namespaced_config_map.return_value = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name="prometheus"), data={"prometheus.yml": yaml.dump(prometheus_config)}
        )
        self.assertEqual(self.orchestrator.get_prometheus_scrape_values(), ("15s", "15s", "10s"))
        self.orchestrator.set_prometheus_scrape_values("5s", "5s", "3s")
        written = self.core.patch_namespaced_config_map.call_args.kwargs["body"].data["prometheus.yml"]
        self.assertEqual(yaml.safe_load(written)["global"]["scrape_interval"], "5s")
        restart.assert_called_once_with(PROMETHEUS)
