"""Test the live Grafana dashboard of --dashboard"""

import json
import unittest
from unittest import mock

import yaml
from kubernetes.client.rest import ApiException

from oxn.cli.argparser import parse_oxn_args
from oxn.common.errors import OrchestratorException
from oxn.core.engine import Engine
from oxn.core.matrix import Variant
from oxn.core.runner import ExperimentRunner
from oxn.core.validation import validate_syntax
from oxn.models.experiment_spec import ExperimentSpec, PrometheusService, ServiceReference
from oxn.observability import dashboard
from oxn.observability.dashboard import (
    RunDashboard,
    build_dashboard,
    build_datasource,
    datasource_uid,
    started_treatments,
)
from oxn.tests.unit.test_deployment import single_variant

SPEC = """
experiment:
  version: 0.0.1
  orchestrator: kubernetes
  services:
    jaeger: {name: jaeger, namespace: system-under-evaluation}
    grafana: {name: grafana, namespace: monitoring}
    prometheus:
      - {name: prometheus, namespace: system-under-evaluation, target: sue}
      - {name: kube-prometheus-kube-prome-prometheus, namespace: oxn-external-monitoring, target: oxn}
  responses:
    - recommendations:
        type: metric
        target: sue
        metric_name: app_recommendations_counter_total
        labels: {service: recommendation}
        left_window: 240s
        right_window: 60s
        step: 5
    - energy:
        type: metric
        target: oxn
        metric_name: sum(kepler_container_joules_total)
        left_window: 420s
        right_window: 120s
        step: 30
    - frontend_traces:
        type: trace
        service_name: frontend
        left_window: 10s
        right_window: 10s
  treatments:
    - empty_treatment:
        action: empty
        params: {duration: 1m}
  sue:
    required: []
  loadgen:
    run_time: 10m
    locust_files: [{path: locust/locust_basic_interaction.py}]
    target: {name: frontend-proxy, namespace: system-under-evaluation, port: 8080}
"""

SUE = PrometheusService(name="prometheus", namespace="system-under-evaluation", target="sue")
OXN = PrometheusService(name="kube-prometheus-kube-prome-prometheus", namespace="oxn-external-monitoring", target="oxn")
START = 1_800_000_000.0


def spec() -> ExperimentSpec:
    return validate_syntax(yaml.safe_load(SPEC))


def treatment(name, action, start=None, end=None):
    """A treatment as the dashboard reads it"""
    t = mock.MagicMock(action=action, start=start, end=end)
    t.name = name
    return t


def fake_orchestrator() -> mock.MagicMock:
    """An orchestrator for SPEC: Prometheus of a target at http://<target>:9090/, Grafana from services.grafana"""
    o = mock.MagicMock()
    o.get_prometheus_url.side_effect = lambda target, internal=False: f"http://{target}:9090/"
    o.get_grafana_service.return_value = ServiceReference(name="grafana", namespace="monitoring")
    return o


def runner(treatments=(), end=None, levels=None, config=None, orchestrator=None) -> ExperimentRunner:
    """A runner whose load started at START, without built treatments or observer"""
    with mock.patch("oxn.core.runner.Observer"), mock.patch.object(ExperimentRunner, "_build_treatments"):
        r = ExperimentRunner(
            orchestrator=orchestrator if orchestrator is not None else fake_orchestrator(),
            config=config if config is not None else spec(),
            config_filename="experiments/test.yml",
            variant=Variant(levels=levels or {}, values=dict(levels or {})),
        )
    r.id = "ab12cd34" * 4
    r.experiment_start = START
    r.experiment_end = end
    r.treatments = {t.name: t for t in treatments}
    return r


def api_error(status: int) -> ApiException:
    return ApiException(status=status, reason="reason")


class DatasourceTest(unittest.TestCase):
    def test_the_uid_depends_on_the_service_not_on_its_target(self):
        renamed = PrometheusService(name=SUE.name, namespace=SUE.namespace, target="other")
        self.assertEqual(datasource_uid(SUE), datasource_uid(renamed))
        self.assertNotEqual(datasource_uid(SUE), datasource_uid(OXN))
        self.assertLessEqual(len(datasource_uid(SUE)), 40)

    def test_grafana_reaches_prometheus_at_the_given_url(self):
        (source,) = build_datasource(SUE, "http://prometheus.system-under-evaluation:9090/")["datasources"]
        self.assertEqual(source["url"], "http://prometheus.system-under-evaluation:9090/")
        self.assertEqual(source["type"], "prometheus")
        self.assertEqual(source["uid"], datasource_uid(SUE))


class BuildDashboardTest(unittest.TestCase):
    # the longest left window of all responses is the 420s of energy, the longest right window its 120s
    FROM = "2027-01-15T07:53:00.000Z"

    def test_a_live_dashboard_ends_now_and_refreshes(self):
        board = build_dashboard(runner())
        self.assertEqual(board["time"], {"from": self.FROM, "to": "now"})
        self.assertEqual(board["refresh"], dashboard.LIVE_REFRESH)

    def test_once_the_load_ended_a_live_dashboard_ends_with_the_right_window(self):
        board = build_dashboard(runner(end=START + 600))
        self.assertEqual(board["time"], {"from": self.FROM, "to": "2027-01-15T08:12:00.000Z"})
        self.assertEqual(board["refresh"], dashboard.LIVE_REFRESH)

    def test_a_pinned_dashboard_does_not_refresh(self):
        board = build_dashboard(runner(end=START + 600), pinned_at=START + 720)
        self.assertEqual(board["time"]["to"], "2027-01-15T08:12:00.000Z")
        self.assertEqual(board["refresh"], "")

    def test_every_metric_response_is_a_panel_on_the_prometheus_of_its_target(self):
        board = build_dashboard(runner())
        panels = [p for p in board["panels"] if p["type"] == "timeseries"]
        self.assertEqual([p["title"] for p in panels], ["recommendations", "energy"])
        self.assertEqual(panels[0]["datasource"]["uid"], datasource_uid(SUE))
        self.assertEqual(panels[1]["datasource"]["uid"], datasource_uid(OXN))
        self.assertEqual(
            panels[0]["targets"][0]["expr"], 'app_recommendations_counter_total{service="recommendation",}'
        )
        self.assertEqual([p["interval"] for p in panels], ["5s", "30s"])
        self.assertEqual(len({p["id"] for p in board["panels"]}), len(board["panels"]))

    def test_the_summary_names_the_run_variant_treatments_and_trace_responses(self):
        board = build_dashboard(runner([treatment("pause", "empty", start=START)], levels={"sampling": "10"}))
        summary = board["panels"][0]["options"]["content"]
        for text in ("experiments/test.yml", "ab12cd34", "`sampling=10`", "| pause | `empty` |", "`frontend_traces`"):
            self.assertIn(text, summary)
        self.assertEqual(board["title"], "test · sampling=10 · ab12cd34")
        self.assertEqual(board["tags"], ["oxn", "test", "sampling=10"])

    def test_the_uid_is_the_same_for_every_update_of_a_run(self):
        uids = {build_dashboard(runner())["uid"], build_dashboard(runner(end=START), pinned_at=START)["uid"]}
        self.assertEqual(len(uids), 1)
        self.assertLessEqual(len(uids.pop()), 40)

    def test_only_started_treatments_are_shown_in_the_order_they_started(self):
        r = runner(
            [
                treatment("later", "empty", start=START + 10),
                treatment("earlier", "kube_probl", start=START - 10, end=START),
                treatment("pending", "empty"),
            ]
        )
        self.assertEqual([t.name for t in started_treatments(r)], ["earlier", "later"])
        self.assertEqual(len(build_dashboard(r)["annotations"]["list"]), 2)

    def test_treatments_are_bands_on_the_prometheus_of_target_oxn(self):
        r = runner(
            [
                treatment("sampling", "kube_probl", start=START - 60, end=START - 30),
                treatment("pause", "empty", start=START),
            ]
        )
        markers = build_dashboard(r)["annotations"]["list"]
        self.assertEqual(
            [m["expr"] for m in markers], ["vector(time()) > 1799999940 < 1799999970", "vector(time()) > 1800000000"]
        )
        self.assertEqual({m["datasource"]["uid"] for m in markers}, {datasource_uid(OXN)})
        self.assertEqual(markers[0]["titleFormat"], "sampling (kube_probl)")

    def test_without_target_oxn_the_markers_use_the_first_prometheus(self):
        only_sue = spec()
        assert only_sue.experiment.services is not None
        only_sue.experiment.services.prometheus = [SUE]
        only_sue.experiment.responses = [
            r for r in only_sue.experiment.responses if getattr(r, "target", "sue") == "sue"
        ]
        r = runner([treatment("pause", "empty", start=START)], config=only_sue)
        (marker,) = build_dashboard(r)["annotations"]["list"]
        self.assertEqual(marker["datasource"]["uid"], datasource_uid(SUE))


class RunDashboardTest(unittest.TestCase):
    def setUp(self):
        self.orchestrator = fake_orchestrator()
        self.kube = self.orchestrator.kube_client
        self.runner = runner([treatment("pause", "empty", start=START)], orchestrator=self.orchestrator)
        self.board = RunDashboard(self.orchestrator, self.runner)

    def started(self):
        """Start the dashboard and forget the ConfigMaps start() wrote"""
        self.board.start()
        self.kube.reset_mock()

    def written(self, method="create_namespaced_config_map"):
        return {c.kwargs["body"].metadata.name: c.kwargs["body"] for c in getattr(self.kube, method).call_args_list}

    def dashboard_json(self):
        return json.loads(self.written()["oxn-dashboard-ab12cd34"].data["oxn-run-ab12cd34ab12cd34.json"])

    def test_start_writes_a_datasource_per_prometheus_and_the_dashboard(self):
        self.board.start()
        self.kube.read_namespaced_service.assert_called_once_with("grafana", "monitoring")
        written = self.written()
        self.assertEqual(len(written), 3)
        # in the namespace of the spec's Grafana, where its sidecars look
        self.assertEqual({m.metadata.namespace for m in written.values()}, {"monitoring"})
        dashboard_map = written["oxn-dashboard-ab12cd34"]
        self.assertEqual(dashboard_map.metadata.labels["grafana_dashboard"], "1")
        self.assertEqual(dashboard_map.metadata.labels["oxn/run"], "ab12cd34")
        self.assertEqual(self.dashboard_json()["time"]["to"], "now")
        sources = [m for name, m in written.items() if name.startswith("oxn-datasource-")]
        self.assertEqual(len(sources), 2)
        urls = {yaml.safe_load(m.data["datasource.yaml"])["datasources"][0]["url"] for m in sources}
        self.assertEqual(urls, {"http://sue:9090/", "http://oxn:9090/"})
        self.orchestrator.get_prometheus_url.assert_any_call("sue", internal=True)
        self.assertTrue(all(m.metadata.labels["grafana_datasource"] == "1" for m in sources))

    def test_nothing_is_written_before_start(self):
        self.board.update()
        self.board.finish()
        self.kube.create_namespaced_config_map.assert_not_called()

    def test_an_existing_configmap_is_replaced(self):
        self.started()
        self.kube.create_namespaced_config_map.side_effect = api_error(409)
        self.board.update()
        self.assertEqual(list(self.written("replace_namespaced_config_map")), ["oxn-dashboard-ab12cd34"])

    def test_without_the_grafana_service_nothing_is_written(self):
        self.kube.read_namespaced_service.side_effect = api_error(404)
        with self.assertLogs(dashboard.logger, "WARNING"):
            self.board.start()
        self.board.update()
        self.board.finish()
        self.kube.create_namespaced_config_map.assert_not_called()

    def test_without_grafana_in_the_spec_nothing_is_written(self):
        self.orchestrator.get_grafana_service.side_effect = OrchestratorException(
            message="The spec has no experiment.services.grafana"
        )
        with self.assertLogs(dashboard.logger, "WARNING") as logs:
            self.board.start()
        self.assertIn("services.grafana", logs.output[0])
        self.board.update()
        self.kube.read_namespaced_service.assert_not_called()
        self.kube.create_namespaced_config_map.assert_not_called()

    def test_a_failed_write_is_a_warning_not_an_error(self):
        self.started()
        self.kube.create_namespaced_config_map.side_effect = api_error(403)
        with self.assertLogs(dashboard.logger, "WARNING"):
            self.board.update()

    def test_finish_pins_a_complete_run_to_the_observed_window_once(self):
        self.started()
        self.runner.experiment_end = START + 600
        self.board.finish()
        self.board.finish()
        self.assertEqual(self.kube.create_namespaced_config_map.call_count, 1)
        board = self.dashboard_json()
        self.assertEqual(board["refresh"], "")
        self.assertEqual(board["time"]["to"], "2027-01-15T08:12:00.000Z")

    def test_finish_pins_a_run_that_failed_during_its_load_to_now(self):
        self.started()
        with mock.patch("oxn.observability.dashboard.utc_timestamp", return_value=START + 60):
            self.board.finish()
        self.assertEqual(self.dashboard_json()["time"]["to"], "2027-01-15T08:01:00.000Z")


class RunnerHookTest(unittest.TestCase):
    def test_on_change_is_called_when_each_runtime_treatment_starts_and_ends(self):
        with (
            mock.patch("oxn.core.runner.Observer") as observer,
            mock.patch.object(ExperimentRunner, "_build_treatments"),
        ):
            observer.return_value.time_to_wait_left.return_value = 0
            runner = ExperimentRunner(orchestrator=mock.MagicMock(), config=mock.MagicMock())
        seen = []
        treatment = mock.MagicMock(start=None, end=None)
        treatment.is_runtime.return_value = True
        treatment.inject.side_effect = lambda: seen.append("inject")
        runner.treatments = {"t": treatment}
        runner.execute_runtime_treatments(on_change=lambda: seen.append((treatment.start is not None, treatment.end)))
        self.assertEqual(seen[0], (True, None))
        self.assertEqual(seen[1], "inject")
        self.assertIsNotNone(seen[2][1])


class EngineDashboardTest(unittest.TestCase):
    def _run(self, dashboard_flag, observe_error=None):
        runner = mock.MagicMock()
        runner.treatments = {}
        runner.observer.variables.return_value = {}
        runner.observe_response_variables.side_effect = observe_error
        engine = Engine(configuration_path="spec.yml", report_path="reports/", dashboard=dashboard_flag)
        engine.variants = single_variant()
        engine.reporter = mock.MagicMock()
        with (
            mock.patch("oxn.core.engine.KubernetesOrchestrator"),
            mock.patch("oxn.core.engine.LocustKubernetesLoadgenerator"),
            mock.patch("oxn.core.engine.ExperimentRunner", return_value=runner),
            mock.patch("oxn.core.engine.RunDashboard") as board_class,
        ):
            try:
                engine.run(runs=1, orchestration_timeout=1)
            except BaseException:  # noqa: BLE001, the interrupt the test injects
                pass
        return engine, runner, board_class

    def test_without_the_flag_there_is_no_dashboard(self):
        _, runner, board_class = self._run(dashboard_flag=False)
        board_class.assert_not_called()
        self.assertIsNone(runner.execute_runtime_treatments.call_args.kwargs["on_change"])

    def test_a_run_starts_updates_and_pins_its_dashboard(self):
        engine, runner, board_class = self._run(dashboard_flag=True)
        board = board_class.return_value
        self.assertIs(board_class.call_args.kwargs["runner"], runner)
        self.assertIs(board_class.call_args.kwargs["orchestrator"], engine.orchestrator)
        board.start.assert_called_once()
        self.assertEqual(runner.execute_runtime_treatments.call_args.kwargs["on_change"], board.update)
        board.finish.assert_called_once_with()
        self.assertIsNone(engine.run_dashboard)

    def test_a_failed_run_pins_its_dashboard_at_teardown(self):
        engine, _, board_class = self._run(dashboard_flag=True, observe_error=KeyboardInterrupt)
        board_class.return_value.finish.assert_not_called()
        engine.teardown()
        board_class.return_value.finish.assert_called_once_with()
        self.assertIsNone(engine.run_dashboard)


class DashboardFlagTest(unittest.TestCase):
    @mock.patch("os.path.exists", return_value=True)
    def test_the_dashboard_is_opt_in(self, _):
        self.assertFalse(parse_oxn_args(["spec.yml"]).dashboard)
        self.assertTrue(parse_oxn_args(["spec.yml", "--dashboard"]).dashboard)
