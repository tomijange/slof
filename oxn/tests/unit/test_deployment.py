import glob
import os
import unittest
from unittest import mock

from kubernetes.client.exceptions import ApiException

from oxn.common.errors import DeploymentException, OxnException
from oxn.core.engine import Engine
from oxn.core.validation import load_experiment_specification, read_experiment_specification, validate_syntax
from oxn.models.experiment_spec import DeploymentDescription
from oxn.orchestration.deployment import Deployment

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

description = {
    "namespaces": [{"name": "system-under-evaluation", "labels": {"istio-injection": "enabled"}}],
    "steps": [
        {
            "helm": {
                "release": "kube-prometheus",
                "chart": "kube-prometheus-stack",
                "repo": "https://prometheus-community.github.io/helm-charts",
                "version": "62.5.1",
                "namespace": "oxn-external-monitoring",
                "values": ["values_kube_prometheus.yaml"],
            }
        },
        {
            "manifests": {
                "paths": ["k8s/elasticsearch/"],
                "namespace": "system-under-evaluation",
                "wait_for": ["deployment/elasticsearch"],
            }
        },
        {
            "helm": {
                "release": "astronomy-shop",
                "chart": "opentelemetry-demo",
                "namespace": "system-under-evaluation",
                "values": ["values_opentelemetry_demo.yaml"],
                "set": {"components.recommendation.resources.limits.cpu": "500m"},
            }
        },
    ],
}


def not_found():
    return ApiException(status=404)


class DeploymentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.commands = []
        self.failing = set()
        self.deployment = self._deployment()
        which = mock.patch("oxn.orchestration.deployment.shutil.which", return_value="/usr/bin/tool")
        which.start()
        self.addCleanup(which.stop)

    def _deployment(self):
        def run(command):
            self.commands.append(command)
            if command[:2] == ["helm", "status"] and command[2] in self.failing:
                raise DeploymentException(message="not installed")
            return ""

        deployment = Deployment(DeploymentDescription.model_validate(description), run=run)
        deployment._core = mock.MagicMock()
        return deployment

    def test_it_builds_the_helm_install_command(self):
        command = self.deployment.steps[0].install_command()
        self.assertEqual(command[:5], ["helm", "upgrade", "--install", "kube-prometheus", "kube-prometheus-stack"])
        self.assertIn("--repo", command)
        self.assertEqual(command[command.index("--version") + 1], "62.5.1")
        self.assertEqual(command[command.index("--values") + 1], "values_kube_prometheus.yaml")
        self.assertIn("--wait", command)

    def test_it_passes_set_overrides_as_json(self):
        command = self.deployment.release("astronomy-shop").install_command()
        self.assertIn('components.recommendation.resources.limits.cpu="500m"', command)

    def test_release_overrides_can_be_changed_before_deploying(self):
        self.deployment.release("astronomy-shop").set["components.ad.enabled"] = False
        command = self.deployment.release("astronomy-shop").install_command()
        self.assertIn("components.ad.enabled=false", command)

    def test_it_raises_for_unknown_releases(self):
        with self.assertRaises(OxnException):
            self.deployment.release("does-not-exist")

    def test_it_deploys_steps_in_order(self):
        self.deployment._core.read_namespace.side_effect = not_found()
        self.deployment.deploy()
        self.assertEqual(
            [c[:3] for c in self.commands],
            [
                ["helm", "upgrade", "--install"],
                ["kubectl", "apply", "--namespace"],
                ["kubectl", "rollout", "status"],
                ["helm", "upgrade", "--install"],
            ],
        )
        created = self.deployment._core.create_namespace.call_args.args[0]
        self.assertEqual(created.metadata.name, "system-under-evaluation")
        self.assertEqual(created.metadata.labels, {"istio-injection": "enabled"})

    def test_it_labels_existing_namespaces(self):
        self.deployment.deploy()
        self.deployment._core.create_namespace.assert_not_called()
        self.deployment._core.patch_namespace.assert_called_once_with(
            "system-under-evaluation", {"metadata": {"labels": {"istio-injection": "enabled"}}}
        )

    def test_it_tears_down_in_reverse_order(self):
        self.deployment._core.read_namespace.side_effect = not_found()
        self.deployment.teardown()
        self.assertEqual(
            [c[:3] for c in self.commands],
            [
                ["helm", "status", "astronomy-shop"],
                ["helm", "uninstall", "astronomy-shop"],
                ["kubectl", "delete", "--namespace"],
                ["helm", "status", "kube-prometheus"],
                ["helm", "uninstall", "kube-prometheus"],
            ],
        )
        self.deployment._core.delete_namespace.assert_called_once_with("system-under-evaluation")
        self.deployment._core.delete_collection_namespaced_persistent_volume_claim.assert_any_call(
            namespace="system-under-evaluation", label_selector="app.kubernetes.io/instance=astronomy-shop"
        )

    def test_teardown_skips_releases_that_are_not_installed(self):
        self.failing = {"astronomy-shop", "kube-prometheus"}
        self.deployment._core.delete_namespace.side_effect = not_found()
        self.deployment.teardown()
        self.assertFalse(any(c[:2] == ["helm", "uninstall"] for c in self.commands))

    def test_it_reports_missing_tools(self):
        with mock.patch("oxn.orchestration.deployment.shutil.which", return_value=None):
            with self.assertRaises(DeploymentException):
                self.deployment.deploy()


class DeploymentSchemaTest(unittest.TestCase):
    def _spec(self, deployment):
        spec = read_experiment_specification(os.path.join(REPO_ROOT, "experiments", "test.yml"))
        spec["experiment"]["deployment"] = deployment
        return spec

    def test_the_experiment_schema_accepts_a_deployment_section(self):
        validate_syntax(self._spec(description))

    def test_the_experiment_schema_rejects_invalid_steps(self):
        with self.assertRaises(OxnException):
            validate_syntax(self._spec({"steps": [{"helm": {"release": "missing-chart-and-namespace"}}]}))

    def test_the_experiment_schema_rejects_paths_to_deployment_files(self):
        with self.assertRaises(OxnException):
            validate_syntax(self._spec("deployments/persistence.yml"))

    def test_experiment_specs_without_deployment_have_none(self):
        spec = self._spec(description)
        del spec["experiment"]["deployment"]
        self.assertIsNone(Deployment.from_experiment_spec(validate_syntax(spec)))


class ShippedExperimentsTest(unittest.TestCase):
    def test_the_documented_spec_has_a_deployment(self):
        path = os.path.join(REPO_ROOT, "experiments", "test.yml")
        self.assertIsNotNone(Deployment.from_experiment_spec(load_experiment_specification(path)))

    def test_shipped_deployments_deploy_their_sue_with_existing_files(self):
        paths = glob.glob(os.path.join(REPO_ROOT, "experiments", "*.yml"))
        self.assertTrue(paths)
        for path in sorted(paths):
            with self.subTest(path=os.path.basename(path)):
                deployment = Deployment.from_experiment_spec(load_experiment_specification(path))
                if deployment is None:
                    continue
                self.assertEqual(deployment.steps[-1].release, "astronomy-shop")
                for step in deployment.steps:
                    for local_path in getattr(step, "values", []) + getattr(step, "paths", []):
                        self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, local_path)), local_path)


class EngineOrderTest(unittest.TestCase):
    def _call_order(self, orchestrator, orchestrator_class):
        calls = mock.MagicMock()
        calls.generator.side_effect = KeyboardInterrupt
        calls.runner.return_value.treatments = {}
        engine = Engine(configuration_path="spec.yml", report_path="reports/")
        engine.spec = mock.MagicMock()
        engine.spec.experiment.orchestrator = orchestrator
        with mock.patch(f"oxn.core.engine.{orchestrator_class}", calls.orchestrator), mock.patch(
            "oxn.core.engine.LocustKubernetesLoadgenerator", calls.generator
        ), mock.patch("oxn.core.engine.ExperimentRunner", calls.runner):
            with self.assertRaises(KeyboardInterrupt):
                engine.run(runs=1, orchestration_timeout=1)
        self.assertTrue(engine.sue_running)
        return [name for name, _, _ in calls.mock_calls]

    def test_kubernetes_treatments_and_the_load_generator_need_the_deployed_sue(self):
        names = self._call_order("kubernetes", "KubernetesOrchestrator")
        self.assertLess(names.index("orchestrator().orchestrate"), names.index("runner().execute_compile_time_treatments"))
        self.assertLess(names.index("runner().execute_compile_time_treatments"), names.index("generator"))

    def test_docker_compose_treatments_run_before_the_sue_is_built(self):
        names = self._call_order("docker-compose", "DockerComposeOrchestrator")
        self.assertLess(names.index("runner().execute_compile_time_treatments"), names.index("orchestrator().orchestrate"))


class EngineMissingResponseTest(unittest.TestCase):
    def test_responses_without_data_are_neither_stored_nor_reported(self):
        captured = mock.MagicMock(data=mock.MagicMock(__len__=lambda _: 1))
        captured.name = "captured"
        missing = mock.MagicMock(data=None)
        missing.name = "missing"
        runner = mock.MagicMock()
        runner.treatments = {"treatment": mock.MagicMock()}
        runner.observer.variables.return_value = {"captured": captured, "missing": missing}
        engine = Engine(configuration_path="spec.yml", report_path="reports/")
        engine.spec = mock.MagicMock()
        engine.spec.experiment.orchestrator = "kubernetes"
        engine.reporter = mock.MagicMock()
        with mock.patch("oxn.core.engine.KubernetesOrchestrator"), mock.patch(
            "oxn.core.engine.LocustKubernetesLoadgenerator"
        ), mock.patch("oxn.core.engine.ExperimentRunner", return_value=runner), mock.patch(
            "oxn.core.engine.write_dataframe"
        ) as write_dataframe:
            engine.run(runs=1, orchestration_timeout=1)
        self.assertEqual([c.kwargs["response_key"] for c in write_dataframe.call_args_list], ["captured"])
        self.assertEqual([c.kwargs["response"] for c in engine.reporter.gather_interaction.call_args_list], [captured])
