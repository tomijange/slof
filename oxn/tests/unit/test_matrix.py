"""Test the matrix section of experiment specs and running its variants"""

import argparse
import os
import tempfile
import unittest
from unittest import mock

import pydantic
import yaml

from oxn.cli.argparser import parse_oxn_args
from oxn.cli.plan import describe_plan, expanded_specs, format_duration
from oxn.common.errors import OxnException
from oxn.core.engine import Engine
from oxn.core.matrix import MatrixError, Variant, expand
from oxn.core.runner import ExperimentRunner
from oxn.core.validation import ExperimentVariant, load_experiment_specification, load_variants
from oxn.reporting.report import Reporter
from oxn.tests.unit.spec_mocks import kubernetes_experiment
from oxn.treatments.runtime.empty import EmptyParams

MATRIX = """
matrix:
  sampling: [5.0, 10.0]
  storage:
    memory:
      values: deployments/values/values_opentelemetry_demo.yaml
      steps: []
    elasticsearch:
      values: deployments/values/values_opentelemetry_demo_persistence.yaml
      steps:
        - manifests: {paths: [k8s/elasticsearch/], wait_for: [deployment/elasticsearch]}
experiment:
  steps:
    - ${{ storage.steps }}
    - helm: {release: astronomy-shop, values: ["${{ storage.values }}"]}
  params:
    sampling_percentage: ${{ sampling }}
    label: sampling-${{ sampling }}
"""


def expanded(text=MATRIX, only=()):
    return expand(yaml.safe_load(text), only)


def expand_error(text, only=()) -> str:
    """The message of the error that expanding text raises"""
    try:
        expanded(text, only)
    except (MatrixError, pydantic.ValidationError) as e:
        return str(e)
    raise AssertionError("no error raised")


class ExpansionTest(unittest.TestCase):
    def test_it_builds_every_combination_in_axis_order(self):
        self.assertEqual(
            [variant.id for variant, _ in expanded()],
            [
                "sampling=5.0,storage=memory",
                "sampling=5.0,storage=elasticsearch",
                "sampling=10.0,storage=memory",
                "sampling=10.0,storage=elasticsearch",
            ],
        )

    def test_it_fills_placeholders_with_typed_values_and_splices_lists(self):
        variants = expanded()
        memory, elasticsearch = variants[0][1]["experiment"], variants[1][1]["experiment"]
        self.assertEqual(
            elasticsearch["steps"],
            [
                {"manifests": {"paths": ["k8s/elasticsearch/"], "wait_for": ["deployment/elasticsearch"]}},
                {
                    "helm": {
                        "release": "astronomy-shop",
                        "values": ["deployments/values/values_opentelemetry_demo_persistence.yaml"],
                    }
                },
            ],
        )
        self.assertEqual(elasticsearch["params"], {"sampling_percentage": 5.0, "label": "sampling-5.0"})
        self.assertEqual([list(step) for step in memory["steps"]], [["helm"]])

    def test_variants_do_not_share_the_matrix_values(self):
        variants = expanded()
        variants[1][1]["experiment"]["steps"][0]["manifests"]["paths"].append("changed")
        self.assertEqual(variants[3][1]["experiment"]["steps"][0]["manifests"]["paths"], ["k8s/elasticsearch/"])

    def test_the_matrix_section_is_not_part_of_the_expanded_spec(self):
        self.assertNotIn("matrix", expanded()[0][1])

    def test_variants_know_their_key_and_factors(self):
        variant = expanded()[3][0]
        self.assertEqual(variant.key("experiments/x.yml"), "experiments/x.yml[sampling=10.0,storage=elasticsearch]")
        self.assertEqual(variant.factors, {"sampling": 10.0, "storage": "elasticsearch"})

    def test_a_spec_without_a_matrix_is_one_variant_without_levels(self):
        self.assertEqual(expand({"experiment": {"a": 1}}), [(Variant(), {"experiment": {"a": 1}})])
        self.assertEqual(Variant().key("experiments/x.yml"), "experiments/x.yml")
        self.assertEqual((Variant().id, Variant().factors), ("", {}))

    def test_booleans_and_scalars_of_named_levels(self):
        variants = expanded("""
matrix:
  istio: [true, false]
  interval: {fast: 5s, slow: 60s}
experiment: {mesh: "${{ istio }}", interval: "${{ interval }}", text: "mesh ${{ istio }}"}
""")
        self.assertEqual(variants[0][0].id, "istio=true,interval=fast")
        self.assertEqual(variants[0][1]["experiment"], {"mesh": True, "interval": "5s", "text": "mesh true"})
        self.assertEqual(variants[3][0].factors, {"istio": False, "interval": "slow"})


class MatrixErrorTest(unittest.TestCase):
    def test_unknown_axis(self):
        self.assertEqual(
            expand_error(MATRIX.replace("${{ sampling }}\n", "${{ samplin }}\n")),
            "experiment.params.sampling_percentage: unknown axis samplin, the matrix has sampling, storage",
        )

    def test_placeholders_without_a_matrix(self):
        self.assertEqual(
            expand_error("experiment: {a: '${{ x }}'}"), "experiment.a: unknown axis x, the spec has no matrix"
        )

    def test_unknown_key_of_a_level(self):
        self.assertEqual(
            expand_error(MATRIX.replace("storage.values", "storage.value")),
            "experiment.steps.1.helm.values.0: ${{ storage.value }} does not exist in every level of storage",
        )

    def test_unused_axis(self):
        self.assertEqual(expand_error(MATRIX.replace("${{ sampling }}", "1")), "No placeholder uses the axis sampling")

    def test_placeholder_in_a_key(self):
        self.assertIn("not in the key ${{ sampling }}", expand_error(MATRIX + "  ${{ sampling }}: 1\n"))

    def test_a_list_or_mapping_inside_a_longer_string(self):
        message = expand_error(MATRIX.replace("sampling-${{ sampling }}", "steps-${{ storage.steps }}"))
        self.assertIn("inside a longer string, ${{ storage.steps }} has to be a scalar", message)

    def test_invalid_placeholder(self):
        self.assertIn("invalid placeholder", expand_error(MATRIX.replace("${{ sampling }}\n", "${{ sampling + 1 }}\n")))

    def test_the_matrix_is_validated_with_pydantic(self):
        for matrix, message in [
            ("{a: [[1]]}", "use a mapping to name such levels"),
            ("{a: ['5 %']}", "String should match pattern"),
            ("{a: []}", "at least 1 item"),
            ("{}", "at least 1 item"),
            ("{1a: [1]}", "String should match pattern"),
            ("[1, 2]", "Input should be a valid dictionary"),
        ]:
            with self.subTest(matrix=matrix):
                self.assertIn(message, expand_error(f"matrix: {matrix}\nexperiment: {{x: '${{{{ a }}}}'}}"))


class SelectionTest(unittest.TestCase):
    def ids(self, *only):
        return [variant.id for variant, _ in expanded(only=only)]

    def test_no_selection_is_every_variant(self):
        self.assertEqual(len(self.ids()), 4)

    def test_levels_of_one_axis_are_alternatives_and_axes_must_all_match(self):
        self.assertEqual(self.ids("storage=memory"), ["sampling=5.0,storage=memory", "sampling=10.0,storage=memory"])
        self.assertEqual(
            self.ids("sampling=5.0", "sampling=10.0", "storage=elasticsearch"),
            ["sampling=5.0,storage=elasticsearch", "sampling=10.0,storage=elasticsearch"],
        )

    def test_unknown_axes_and_levels(self):
        for only in (["mesh=on"], ["sampling"], ["sampling=10"], ["storage=disk"]):
            with self.subTest(only=only):
                self.assertEqual(
                    expand_error(MATRIX, only),
                    f"--only {only[0]}: expected AXIS=LEVEL, the matrix has sampling: 5.0, 10.0; "
                    "storage: memory, elasticsearch",
                )

    def test_a_spec_without_a_matrix_has_nothing_to_select(self):
        self.assertIn("the spec has no matrix", expand_error("experiment: {}", ["a=1"]))


KUBERNETES_MATRIX = """
matrix:
  duration: {short: 1m, long: 2m}
  users: [100, 200]
""" + kubernetes_experiment.replace("duration: 1m", 'duration: "${{ duration }}"').replace(
    "run_time: 10m", "run_time: 10m\n    max_users: ${{ users }}"
)


class LoadVariantsTest(unittest.TestCase):
    def _write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False)
        with handle:
            handle.write(text)
        self.addCleanup(os.remove, handle.name)
        return handle.name

    def test_every_variant_is_validated_into_a_spec(self):
        self.assertIn("${{ duration }}", KUBERNETES_MATRIX)
        variants = load_variants(self._write(KUBERNETES_MATRIX))
        self.assertEqual(
            [(v.variant.id, v.spec.experiment.loadgen.max_users) for v in variants],
            [
                ("duration=short,users=100", 100),
                ("duration=short,users=200", 200),
                ("duration=long,users=100", 100),
                ("duration=long,users=200", 200),
            ],
        )
        self.assertEqual(variants[2].spec.experiment.treatments[0].params, EmptyParams(duration="2m"))
        self.assertEqual(variants[2].raw["experiment"]["loadgen"]["max_users"], 100)

    def test_only_selects_variants(self):
        variants = load_variants(self._write(KUBERNETES_MATRIX), only=["users=200"])
        self.assertEqual([v.variant.id for v in variants], ["duration=short,users=200", "duration=long,users=200"])

    def test_an_invalid_variant_is_named(self):
        path = self._write(KUBERNETES_MATRIX.replace("long: 2m", "long: 2 minutes"))
        with self.assertRaises(OxnException) as raised:
            load_variants(path)
        self.assertIn("Can't validate variant duration=long,users=100", str(raised.exception))
        self.assertIn("duration", str(raised.exception))

    def test_matrix_errors_name_the_spec(self):
        path = self._write(KUBERNETES_MATRIX.replace("${{ users }}", "${{ user }}"))
        with self.assertRaises(OxnException) as raised:
            load_variants(path)
        self.assertIn(f"Can't expand the matrix of {path}", str(raised.exception))

    def test_a_single_spec_cannot_be_loaded_from_a_matrix(self):
        with self.assertRaises(OxnException) as raised:
            load_experiment_specification(self._write(KUBERNETES_MATRIX))
        self.assertIn("has a matrix with 4 variants", str(raised.exception))
        self.assertIsNotNone(load_experiment_specification(self._write(kubernetes_experiment)))


def variant(id_text: str, spec=None) -> ExperimentVariant:
    """A variant of a one-axis matrix like a=1, whose level value is its name"""
    axis, _, label = id_text.partition("=")
    return ExperimentVariant(
        variant=Variant(levels={axis: label}, values={axis: label}),
        spec=spec if spec is not None else mock.MagicMock(),
        raw={"experiment": {"axis": label}},
    )


class EngineScheduleTest(unittest.TestCase):
    def _engine(self, **kwargs):
        engine = Engine(configuration_path="spec.yml", report_path="reports/", **kwargs)
        engine.variants = [variant("a=1"), variant("a=2"), variant("a=3")]
        engine.reporter = mock.MagicMock()
        return engine

    def test_rounds_interleave_the_variants(self):
        schedule = self._engine().schedule(2)
        self.assertEqual([e.variant.id for e in schedule], ["a=1", "a=2", "a=3", "a=1", "a=2", "a=3"])

    def test_randomized_rounds_still_run_every_variant_once_per_round(self):
        schedule = self._engine().schedule(3, randomize_variants=True)
        for round_start in range(0, 9, 3):
            self.assertEqual(
                sorted(e.variant.id for e in schedule[round_start : round_start + 3]), ["a=1", "a=2", "a=3"]
            )

    def test_a_failed_run_is_torn_down_and_the_next_one_starts(self):
        engine = self._engine()
        ran = []

        def run_once(experiment, **_):
            ran.append(experiment.variant.id)
            if experiment.variant.id == "a=2":
                raise OxnException(message="deploy failed")

        with (
            mock.patch.object(engine, "_run_once", side_effect=run_once),
            mock.patch.object(engine, "teardown") as teardown,
        ):
            with self.assertRaises(OxnException) as raised:
                engine.run(runs=1)
        self.assertEqual(ran, ["a=1", "a=2", "a=3"])
        teardown.assert_called_once()
        self.assertIn("1 of 3 runs failed", str(raised.exception))
        self.assertIn("run 2 of 3, variant a=2", str(raised.exception))
        self.assertEqual(engine.reporter.dump_report_data.call_count, 3)

    def test_fail_fast_stops_at_the_first_failed_run(self):
        engine = self._engine(fail_fast=True)
        with mock.patch.object(engine, "_run_once", side_effect=OxnException(message="deploy failed")) as run_once:
            with self.assertRaises(OxnException):
                engine.run(runs=1)
        run_once.assert_called_once()

    def test_each_run_stores_under_the_key_of_its_variant(self):
        engine = self._engine()
        engine.variants = engine.variants[1:2]
        response = mock.MagicMock(data=mock.MagicMock(__len__=lambda _: 1))
        response.name = "cpu"
        with (
            mock.patch("oxn.core.engine.KubernetesOrchestrator"),
            mock.patch("oxn.core.engine.LocustKubernetesLoadgenerator"),
            mock.patch("oxn.core.runner.Observer") as observer,
            mock.patch.object(ExperimentRunner, "_build_treatments"),
            mock.patch("oxn.core.engine.write_dataframe") as write_dataframe,
        ):
            observer.return_value.variables.return_value = {"cpu": response}
            observer.return_value.time_to_wait_left.return_value = 0
            observer.return_value.time_to_wait_right.return_value = 0
            engine.run(runs=1)
        kwargs = write_dataframe.call_args.kwargs
        self.assertEqual(kwargs["experiment_key"], "spec.yml[a=2]")
        self.assertEqual(kwargs["metadata"]["factors"], {"a": "2"})
        self.assertEqual(kwargs["metadata"]["variant"], "a=2")
        engine.reporter.begin_run.assert_called_once_with(engine.runner)


class RunnerAndReportTest(unittest.TestCase):
    def _runner(self, variant_value=None, config_filename="experiments/x.yml"):
        with mock.patch("oxn.core.runner.Observer"), mock.patch.object(ExperimentRunner, "_build_treatments"):
            return ExperimentRunner(
                orchestrator=mock.MagicMock(),
                config=mock.MagicMock(),
                config_filename=config_filename,
                variant=variant_value,
            )

    def test_variants_of_one_spec_have_their_own_key_and_hash(self):
        (first, _), (second, _) = expanded()[:2]
        plain, a, b = self._runner(), self._runner(first), self._runner(second)
        self.assertEqual(plain.experiment_key, "experiments/x.yml")
        self.assertEqual(a.experiment_key, "experiments/x.yml[sampling=5.0,storage=memory]")
        self.assertEqual(len({plain.hash, a.hash, b.hash}), 3)
        self.assertIsNone(self._runner(config_filename=None).experiment_key)

    def test_the_report_records_the_variant_of_each_run_and_only_its_interactions(self):
        reporter = Reporter(report_path="reports/")
        reporter.interactions = ["from an earlier run"]
        runner = self._runner(expanded()[3][0])
        reporter.begin_run(runner)
        reporter.assemble_interaction_data(run_key=runner.short_id)
        run = reporter.report_data["report"]["runs"][runner.short_id]
        self.assertEqual(run["variant"], "sampling=10.0,storage=elasticsearch")
        self.assertEqual(run["factors"], {"sampling": 10.0, "storage": "elasticsearch"})
        self.assertEqual(run["interactions"], {})

    def test_the_report_of_a_spec_without_a_matrix_has_no_variant(self):
        reporter = Reporter(report_path="reports/")
        runner = self._runner()
        reporter.begin_run(runner)
        self.assertEqual(reporter.report_data["report"]["runs"][runner.short_id], {})


class CommandLineTest(unittest.TestCase):
    @mock.patch("os.path.exists", return_value=True)
    def test_run_options(self, _):
        args = parse_oxn_args(["spec.yml", "--only", "a=1", "--only", "b=x", "--randomize-variants", "--fail-fast"])
        self.assertEqual((args.only, args.randomize_variants, args.fail_fast), (["a=1", "b=x"], True, True))
        args = parse_oxn_args(["spec.yml"])
        self.assertEqual((args.only, args.randomize_variants, args.fail_fast), ([], False, False))

    @mock.patch("os.path.exists", return_value=True)
    def test_plan_deploy_and_teardown_select_variants(self, _):
        args = parse_oxn_args(["plan", "spec.yml", "--only", "a=1", "--times", "3", "--print"])
        self.assertEqual((args.command, args.only, args.times, args.print_specs), ("plan", ["a=1"], 3, True))
        self.assertEqual(parse_oxn_args(["plan", "spec.yml"]).log_level, "warning")
        for command in ("deploy", "teardown"):
            self.assertEqual(parse_oxn_args([command, "spec.yml", "--only", "a=1"]).only, ["a=1"])


class ManageSueTest(unittest.TestCase):
    def _manage(self, variants):
        from oxn.cli.main import manage_sue

        with (
            mock.patch("oxn.cli.main.load_variants", return_value=variants),
            mock.patch("oxn.cli.main.Deployment") as deployment,
        ):
            manage_sue(argparse.Namespace(spec="spec.yml", only=[], command="deploy"))
        return deployment

    def _variant(self, id_text, deployment):
        spec = mock.MagicMock()
        spec.experiment.deployment = deployment
        return variant(id_text, spec)

    def test_variants_with_the_same_deployment_deploy_it(self):
        deployment = self._manage([self._variant("a=1", "same"), self._variant("a=2", "same")])
        deployment.from_experiment_spec.return_value.deploy.assert_called_once()

    def test_variants_with_different_deployments_need_a_selection(self):
        with self.assertRaises(OxnException) as raised:
            self._manage([self._variant("a=1", "memory"), self._variant("a=2", "elasticsearch")])
        self.assertIn("2 different setups", str(raised.exception))
        self.assertIn("a=1; a=2", str(raised.exception))


class PlanTest(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(
            [format_duration(s) for s in (30, 600, 630, 3600, 4200, 58800)],
            ["30s", "10m", "10m30s", "1h", "1h10m", "16h20m"],
        )

    def _variants(self, *pairs):
        result = []
        for id_text, run_time in pairs:
            spec = mock.MagicMock()
            spec.experiment.loadgen.run_time = run_time
            result.append(variant(id_text, spec))
        return result

    def test_it_lists_variants_and_the_load_time(self):
        text = describe_plan("x.yml", self._variants(("a=1", "70m"), ("a=2", "10m")), times=2)
        self.assertEqual(
            text.splitlines(),
            [
                "x.yml: 2 variants x 2 runs = 4 runs, 2h40m of load plus deployment and teardown",
                "  a=1  1h10m",
                "  a=2  10m",
                "Every round runs each variant once, in this order, 2 rounds",
            ],
        )

    def test_a_spec_without_a_matrix(self):
        spec = mock.MagicMock()
        spec.experiment.loadgen.run_time = "6m"
        variants = [ExperimentVariant(variant=Variant(), spec=spec, raw={"experiment": {}})]
        self.assertEqual(
            describe_plan("t.yml", variants, times=1),
            "t.yml: no matrix, 1 run, 6m of load plus deployment and teardown",
        )

    def test_it_prints_the_expanded_specs_as_yaml_documents(self):
        documents = expanded_specs(self._variants(("a=1", "1m"), ("a=2", "1m")))
        self.assertTrue(documents.startswith("---\n# variant a=1\nexperiment:\n  axis: '1'\n"))
        self.assertEqual([d["experiment"]["axis"] for d in yaml.safe_load_all(documents)], ["1", "2"])
