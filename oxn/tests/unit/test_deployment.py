import glob
import os
import unittest
from unittest import mock

import pydantic
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from oxn.common.errors import DeploymentException, OxnException
from oxn.core.engine import Engine, Phase
from oxn.core.matrix import Variant
from oxn.core.validation import (
    ExperimentVariant,
    load_experiment_specification,
    load_variants,
    read_experiment_specification,
    validate_syntax,
)
from oxn.models.experiment_spec import DeploymentDescription, HelmRelease, ImageBuild
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
        def run(command, input_path=None):
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


def node(name: str, architecture: str) -> client.V1Node:
    return client.V1Node(
        metadata=client.V1ObjectMeta(name=name),
        status=client.V1NodeStatus(
            node_info=client.V1NodeSystemInfo(
                architecture=architecture,
                operating_system="linux",
                boot_id="",
                container_runtime_version="",
                kernel_version="",
                kube_proxy_version="",
                kubelet_version="",
                machine_id="",
                os_image="",
                system_uuid="",
            )
        ),
    )


class ImageStepTest(unittest.TestCase):
    IMAGE = {"name": "slof.local/recommendation-rust:0.1.0", "context": "images/recommendation-rust"}

    def setUp(self) -> None:
        self.commands = []
        self.inputs = []
        self.failing_exec = False
        which = mock.patch("oxn.orchestration.deployment.shutil.which", return_value="/usr/bin/tool")
        which.start()
        self.addCleanup(which.stop)

    def _deployment(self, **image):
        def run(command, input_path=None):
            self.commands.append(command)
            self.inputs.append(input_path)
            if command[:2] == ["kubectl", "exec"] and self.failing_exec:
                raise DeploymentException(message="import failed")
            return ""

        steps = [{"image": {**self.IMAGE, **image}}]
        deployment = Deployment(DeploymentDescription.model_validate({"steps": steps}), run=run)
        deployment._core = mock.MagicMock()
        deployment._core.list_node.return_value = client.V1NodeList(
            items=[node("a", "amd64"), node("b", "amd64"), node("c", "arm64")]
        )
        return deployment

    def test_the_image_needs_a_pinned_tag(self):
        for name in ("recommendation-rust", "recommendation-rust:latest", "localhost:5000/recommendation-rust"):
            with self.subTest(name=name), self.assertRaises(pydantic.ValidationError):
                ImageBuild.model_validate({**self.IMAGE, "name": name})
        for name in ("localhost:5000/r:0.1.0", "ghcr.io/me/r@sha256:abc"):
            with self.subTest(name=name):
                ImageBuild.model_validate({**self.IMAGE, "name": name})

    def test_imported_images_are_built_for_the_nodes(self):
        with self.assertRaises(pydantic.ValidationError):
            ImageBuild.model_validate({**self.IMAGE, "delivery": "import", "platforms": ["linux/amd64"]})

    def test_paths_are_resolved_against_the_spec(self):
        image = ImageBuild.model_validate(
            {**self.IMAGE, "dockerfile": "images/Dockerfile.rust"}, context={"spec_dir": "experiments/slo"}
        )
        self.assertEqual(image.context, "experiments/slo/images/recommendation-rust")
        self.assertEqual(image.dockerfile, "experiments/slo/images/Dockerfile.rust")

    def test_pushed_images_are_built_for_the_platforms_of_the_nodes(self):
        self._deployment(build_args={"PROFILE": "release"}).deploy()
        self.assertEqual(
            self.commands,
            [
                ["docker", "buildx", "build", "--platform", "linux/amd64,linux/arm64"]
                + ["--tag", "slof.local/recommendation-rust:0.1.0", "--build-arg", "PROFILE=release"]
                + ["--output", "type=registry", "images/recommendation-rust"]
            ],
        )

    def test_pushed_images_can_name_their_platforms(self):
        self._deployment(platforms=["linux/riscv64"]).deploy()
        self.assertIn("linux/riscv64", self.commands[0])

    def test_imported_images_are_built_per_platform_and_streamed_into_every_node(self):
        deployment = self._deployment(delivery="import")
        deployment.deploy()

        builds = [c for c in self.commands if c[:2] == ["docker", "buildx"]]
        self.assertEqual([c[c.index("--platform") + 1] for c in builds], ["linux/amd64", "linux/arm64"])
        self.assertTrue(builds[0][builds[0].index("--output") + 1].startswith("type=docker,dest="))

        pods = [call.args[1] for call in deployment._core.create_namespaced_pod.call_args_list]
        self.assertEqual([pod.spec.node_name for pod in pods], ["a", "b", "c"])
        self.assertTrue(pods[0].spec.host_pid)
        self.assertTrue(pods[0].spec.containers[0].security_context.privileged)

        imports = [(c, i) for c, i in zip(self.commands, self.inputs) if c[:2] == ["kubectl", "exec"]]
        self.assertEqual(len(imports), 3)
        command, archive = imports[0]
        self.assertEqual(command[command.index("--") + 1 :][:5], ["nsenter", "-t", "1", "-m", "--"])
        self.assertTrue(archive.endswith("linux-amd64.tar"))
        self.assertTrue(imports[2][1].endswith("linux-arm64.tar"))
        self.assertEqual(deployment._core.delete_namespaced_pod.call_count, 3)

    def test_the_import_pod_is_removed_when_the_import_fails(self):
        deployment = self._deployment(delivery="import")
        self.failing_exec = True
        with self.assertRaises(DeploymentException):
            deployment.deploy()
        deployment._core.delete_namespaced_pod.assert_called_once()

    def test_teardown_keeps_the_image(self):
        self._deployment(delivery="import").teardown()
        self.assertEqual(self.commands, [])

    def test_it_needs_docker(self):
        deployment = self._deployment()

        def which(tool):
            return None if tool == "docker" else "/usr/bin/tool"

        with mock.patch("oxn.orchestration.deployment.shutil.which", side_effect=which):
            with self.assertRaises(DeploymentException) as raised:
                deployment.deploy()
        self.assertIn("docker", str(raised.exception.message))


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
            for experiment in load_variants(path):
                with self.subTest(path=os.path.basename(path), variant=experiment.variant.id):
                    self._check_deployment(experiment.spec)

    def _check_deployment(self, spec):
        deployment = Deployment.from_experiment_spec(spec)
        if deployment is None:
            return
        last_step = deployment.steps[-1]
        assert isinstance(last_step, HelmRelease)
        self.assertEqual(last_step.release, "astronomy-shop")
        for step in deployment.steps:
            for local_path in getattr(step, "values", []) + getattr(step, "paths", []):
                self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, local_path)), local_path)

    def test_the_recommendation_specs_are_matrices(self):
        paths = sorted(glob.glob(os.path.join(REPO_ROOT, "experiments", "recommendation_k8_*.yml")))
        counts = {os.path.basename(path): len(load_variants(path)) for path in paths}
        self.assertEqual(
            counts,
            {
                "recommendation_k8_fault.yml": 8,
                "recommendation_k8_metric_export.yml": 6,
                "recommendation_k8_minimal.yml": 3,
                "recommendation_k8_sampling.yml": 8,
                "recommendation_k8_scrape_mesh.yml": 6,
            },
        )


def single_variant(spec=None) -> list:
    """The variants of a spec without a matrix, for an engine whose spec is not read from a file"""
    return [ExperimentVariant(variant=Variant(), spec=spec if spec is not None else mock.MagicMock(), raw={})]


class EngineOrderTest(unittest.TestCase):
    def _call_order(self, orchestrator, orchestrator_class):
        calls = mock.MagicMock()
        calls.generator.side_effect = KeyboardInterrupt
        calls.runner.return_value.treatments = {}
        engine = Engine(configuration_path="spec.yml", report_path="reports/")
        engine.variants = single_variant()
        with (
            mock.patch(f"oxn.core.engine.{orchestrator_class}", calls.orchestrator),
            mock.patch("oxn.core.engine.LocustKubernetesLoadgenerator", calls.generator),
            mock.patch("oxn.core.engine.ExperimentRunner", calls.runner),
        ):
            with self.assertRaises(KeyboardInterrupt):
                engine.run(runs=1, orchestration_timeout=1)
        self.assertIs(engine.phase, Phase.PREPARATION)
        return [name for name, _, _ in calls.mock_calls]

    def test_kubernetes_treatments_and_the_load_generator_need_the_deployed_sue(self):
        names = self._call_order("kubernetes", "KubernetesOrchestrator")
        self.assertLess(
            names.index("orchestrator().orchestrate"), names.index("runner().execute_compile_time_treatments")
        )
        self.assertLess(names.index("runner().execute_compile_time_treatments"), names.index("generator"))


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
        engine.variants = single_variant()
        engine.reporter = mock.MagicMock()
        with (
            mock.patch("oxn.core.engine.KubernetesOrchestrator"),
            mock.patch("oxn.core.engine.LocustKubernetesLoadgenerator"),
            mock.patch("oxn.core.engine.ExperimentRunner", return_value=runner),
            mock.patch("oxn.core.engine.write_dataframe") as write_dataframe,
        ):
            engine.run(runs=1, orchestration_timeout=1)
        self.assertEqual([c.kwargs["response_key"] for c in write_dataframe.call_args_list], ["captured"])
        self.assertEqual([c.kwargs["response"] for c in engine.reporter.gather_interaction.call_args_list], [captured])


class EnginePhaseTest(unittest.TestCase):
    def _run(self, keep_sue=False, orchestrate_error=None, fail_fast=False):
        runner = mock.MagicMock()
        runner.treatments = {}
        runner.observer.variables.return_value = {}
        engine = Engine(configuration_path="spec.yml", report_path="reports/", keep_sue=keep_sue, fail_fast=fail_fast)
        engine.variants = single_variant()
        engine.reporter = mock.MagicMock()
        phases = []
        enter = engine._enter
        engine._enter = lambda phase: (phases.append(phase), enter(phase))
        with (
            mock.patch("oxn.core.engine.KubernetesOrchestrator") as orchestrator,
            mock.patch("oxn.core.engine.LocustKubernetesLoadgenerator"),
            mock.patch("oxn.core.engine.ExperimentRunner", return_value=runner),
        ):
            orchestrator.return_value.orchestrate.side_effect = orchestrate_error
            try:
                engine.run(runs=1, orchestration_timeout=1)
            except OxnException:
                pass
        return engine, phases, orchestrator.return_value

    def test_a_new_engine_is_in_initialization(self):
        self.assertIs(Engine(configuration_path="spec.yml", report_path="reports/").phase, Phase.INITIALIZATION)

    def test_a_run_passes_through_every_phase(self):
        engine, phases, orchestrator = self._run()
        self.assertEqual(
            phases,
            [Phase.ORCHESTRATION, Phase.PREPARATION, Phase.LOAD, Phase.REPORTING, Phase.TEARDOWN, Phase.COMPLETED],
        )
        orchestrator.teardown.assert_called_once()

    def test_keep_sue_skips_the_teardown_phase(self):
        engine, phases, orchestrator = self._run(keep_sue=True)
        self.assertNotIn(Phase.TEARDOWN, phases)
        self.assertIs(engine.phase, Phase.COMPLETED)
        orchestrator.teardown.assert_not_called()

    def test_a_failed_deploy_is_torn_down_by_the_engine(self):
        engine, _, orchestrator = self._run(orchestrate_error=OxnException(message="deploy failed"))
        self.assertIs(engine.phase, Phase.COMPLETED)
        orchestrator.teardown.assert_called_once()

    def test_with_fail_fast_a_failed_deploy_is_left_to_main_to_tear_down(self):
        engine, _, orchestrator = self._run(orchestrate_error=OxnException(message="deploy failed"), fail_fast=True)
        self.assertIs(engine.phase, Phase.ORCHESTRATION)
        self.assertTrue(engine.phase.sue_deployed)
        orchestrator.teardown.assert_not_called()

    def test_only_initialization_and_completed_have_no_sue(self):
        self.assertEqual([phase for phase in Phase if not phase.sue_deployed], [Phase.INITIALIZATION, Phase.COMPLETED])

    def test_only_the_load_phase_has_a_running_load_generator(self):
        self.assertEqual([phase for phase in Phase if phase.loadgen_running], [Phase.LOAD])


class EngineTeardownTest(unittest.TestCase):
    def _teardown(self, phase, keep_sue=False):
        engine = Engine(configuration_path="spec.yml", report_path="reports/")
        engine.generator = mock.MagicMock()
        engine.orchestrator = mock.MagicMock()
        engine.phase = phase
        engine.keep_sue = keep_sue
        engine.teardown()
        return engine.generator.kill.called, engine.orchestrator.teardown.called

    def test_it_kills_the_load_generator_and_tears_down_the_sue_in_the_load_phase(self):
        self.assertEqual(self._teardown(Phase.LOAD), (True, True))

    def test_it_tears_down_a_partial_deploy(self):
        self.assertEqual(self._teardown(Phase.ORCHESTRATION), (False, True))

    def test_it_retries_a_failed_teardown(self):
        self.assertEqual(self._teardown(Phase.TEARDOWN), (False, True))

    def test_it_cleans_up_nothing_before_the_deploy_or_after_the_run(self):
        self.assertEqual(self._teardown(Phase.INITIALIZATION), (False, False))
        self.assertEqual(self._teardown(Phase.COMPLETED), (False, False))

    def test_it_keeps_the_sue_with_keep_sue(self):
        self.assertEqual(self._teardown(Phase.LOAD, keep_sue=True), (True, False))

    def test_a_successful_teardown_completes_the_run(self):
        engine = Engine(configuration_path="spec.yml", report_path="reports/")
        engine.orchestrator = mock.MagicMock()
        engine.phase = Phase.REPORTING
        engine.teardown()
        self.assertIs(engine.phase, Phase.COMPLETED)

    def test_a_failed_teardown_stays_in_the_teardown_phase(self):
        engine = Engine(configuration_path="spec.yml", report_path="reports/")
        engine.orchestrator = mock.MagicMock()
        engine.orchestrator.teardown.side_effect = OxnException(message="teardown failed")
        engine.phase = Phase.REPORTING
        with self.assertRaises(OxnException):
            engine.teardown()
        self.assertIs(engine.phase, Phase.TEARDOWN)


class MainCleanupTest(unittest.TestCase):
    def _run_experiment(self, error):
        from oxn.cli.main import run_experiment

        with mock.patch("oxn.cli.main.Engine") as engine_class:
            engine = engine_class.return_value
            engine.phase = Phase.LOAD
            engine.run.side_effect = error
            with self.assertRaises(SystemExit) as exited:
                run_experiment(mock.MagicMock(keep_sue=True))
        self.assertEqual(exited.exception.code, 1)
        engine_class.assert_called_once()
        self.assertTrue(engine_class.call_args.kwargs["keep_sue"])
        return engine

    def test_main_tears_down_through_the_engine_after_ctrl_c(self):
        self._run_experiment(KeyboardInterrupt).teardown.assert_called_once_with()

    def test_main_tears_down_through_the_engine_after_an_error(self):
        self._run_experiment(OxnException(message="deploy failed")).teardown.assert_called_once_with()
