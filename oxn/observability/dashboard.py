"""
Purpose: Shows the responses of an experiment run live in Grafana.
Functionality: Builds a Grafana dashboard with one panel per metric response and a marker per treatment, and the
    Grafana datasources of the spec's Prometheus instances. RunDashboard stores both as labelled ConfigMaps, which
    the sidecars of the Grafana in kube-prometheus-stack load without a login.
Connection: Used by oxn.core.engine.Engine with --dashboard. Reads the spec, variant, timestamps and treatments of an
    oxn.core.runner.ExperimentRunner.

While the run lasts, the dashboard refreshes itself and ends at now, or once the load ended, at the end of the right
window. When the responses are observed, it is pinned to the window they were observed in, so it stays as a record of
the run.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

import yaml
from kubernetes import client
from kubernetes.client.rest import ApiException

from oxn.common.errors import OrchestratorException
from oxn.common.settings import GRAFANA_PORT
from oxn.common.utils import time_string_to_seconds, utc_timestamp
from oxn.models.experiment_spec import ExperimentSpec, MetricResponseDescription, PrometheusService
from oxn.models.treatment import Treatment
from oxn.observability.prometheus import Prometheus

if TYPE_CHECKING:
    # only for type hints, the runner does not depend on the observability package the other way round
    from oxn.core.runner import ExperimentRunner
    from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)

DASHBOARD_LABEL = "grafana_dashboard"
"""The label the dashboard sidecar watches for, with the value 1"""
DATASOURCE_LABEL = "grafana_datasource"
"""The label the datasource sidecar watches for, with the value 1"""
LIVE_REFRESH = "10s"
"""How often a live dashboard reloads"""
MARKER_TARGET = "oxn"
"""The Prometheus target the treatment markers query, the external one if the spec has it"""
MARKER_STEP = "15s"
"""Resolution of the treatment markers"""
MARKER_COLORS = ["#F2495C", "#FF9830", "#FADE2A", "#B877D9", "#5794F2", "#73BF69"]
"""Colors of the treatment markers, in the order of the treatments"""


def datasource_uid(service: PrometheusService) -> str:
    """
    The uid of the datasource of a Prometheus service

    Derived from namespace and name, not from the target, so a dashboard keeps reading from the same Prometheus even
    if a later spec gives the target to another one.
    """
    digest = hashlib.sha256(f"{service.namespace}/{service.name}".encode(), usedforsecurity=False).hexdigest()
    return f"oxn-prometheus-{digest[:12]}"


def build_datasource(service: PrometheusService, url: str) -> Dict[str, Any]:
    """The Grafana provisioning file of the datasource of a Prometheus service, which Grafana reaches at url"""
    return {
        "apiVersion": 1,
        "datasources": [
            {
                "name": f"oxn {service.namespace}/{service.name}",
                "type": "prometheus",
                "uid": datasource_uid(service),
                "url": url,
                "access": "proxy",
                "editable": False,
                "jsonData": {"httpMethod": "POST"},
            }
        ],
    }


def dashboard_uid(run_id: str) -> str:
    """The uid of the dashboard of a run, at most 40 characters as Grafana requires"""
    return f"oxn-run-{run_id[:16]}"


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _windows(spec: ExperimentSpec) -> tuple[float, float]:
    """The longest left and right window of the responses, in seconds"""
    responses = spec.experiment.responses
    left = max((time_string_to_seconds(r.left_window) for r in responses), default=0)
    right = max((time_string_to_seconds(r.right_window) for r in responses), default=0)
    return left, right


def _marker_expr(treatment: Treatment) -> str:
    """
    A PromQL expression with one sample per step while the treatment runs

    Grafana draws consecutive samples of an annotation query as one region, so the marker is a band from the start to
    the end of the treatment, and grows with an open one.
    """
    assert treatment.start is not None
    expr = f"vector(time()) > {treatment.start:.0f}"
    if treatment.end is not None:
        expr += f" < {treatment.end:.0f}"
    return expr


def _markers(treatments: Sequence[Treatment], datasource: Dict[str, str]) -> List[Dict[str, Any]]:
    markers = []
    for idx, treatment in enumerate(treatments):
        title = f"{treatment.name} ({treatment.action})"
        markers.append(
            {
                "name": f"Treatment {treatment.name}",
                "datasource": datasource,
                "enable": True,
                "iconColor": MARKER_COLORS[idx % len(MARKER_COLORS)],
                "expr": _marker_expr(treatment),
                "step": MARKER_STEP,
                "titleFormat": title,
                "textFormat": "",
                "tagKeys": "",
                "useValueForTime": False,
                "target": {
                    "refId": "Anno",
                    "expr": _marker_expr(treatment),
                    "interval": MARKER_STEP,
                },
            }
        )
    return markers


def started_treatments(runner: "ExperimentRunner") -> List[Treatment]:
    """The treatments of a run that started so far, in the order they started"""
    started = [t for t in runner.treatments.values() if t.start is not None]
    return sorted(started, key=lambda t: t.start or 0)


def _summary(runner: "ExperimentRunner", treatments: Sequence[Treatment], live: bool) -> str:
    """The markdown of the text panel at the top"""
    assert runner.experiment_start is not None
    lines = [f"**Spec** `{runner.config_filename}` · **run** `{runner.short_id}`"]
    if runner.variant.levels:
        lines.append("**Variant** " + ", ".join(f"`{axis}={level}`" for axis, level in runner.variant.levels.items()))
    status = f"load ended {_iso(runner.experiment_end)}" if runner.experiment_end is not None else "load running"
    if live:
        status += ", refreshes every " + LIVE_REFRESH
    lines.append(f"**Started** {_iso(runner.experiment_start)} · {status}")
    if treatments:
        lines += ["", "| Treatment | Action | Start | End |", "|---|---|---|---|"]
        for treatment in treatments:
            assert treatment.start is not None
            end = _iso(treatment.end) if treatment.end is not None else "running"
            lines.append(f"| {treatment.name} | `{treatment.action}` | {_iso(treatment.start)} | {end} |")
    traces = [r.name for r in runner.config.experiment.responses if r.type == "trace"]
    if traces:
        lines += ["", "Trace responses are not plotted: " + ", ".join(f"`{name}`" for name in traces)]
    return "\n".join(lines)


def _metric_panel(response: MetricResponseDescription, datasource: Dict[str, str], panel_id: int, y: int):
    return {
        "id": panel_id,
        "type": "timeseries",
        "title": response.name,
        "description": f"target {response.target}, step {response.step}s, windows -{response.left_window} "
        f"+{response.right_window}",
        "datasource": datasource,
        "interval": f"{response.step}s",
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
        "targets": [
            {
                "refId": "A",
                "datasource": datasource,
                "expr": Prometheus.build_query(response.metric_name, response.labels),
                "range": True,
            }
        ],
        "fieldConfig": {"defaults": {"custom": {"showPoints": "never"}}, "overrides": []},
        "options": {
            "legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull"]},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def observed_until(runner: "ExperimentRunner") -> Optional[float]:
    """The end of the longest right window of a run, None while its load runs"""
    if runner.experiment_end is None:
        return None
    return runner.experiment_end + _windows(runner.config)[1]


def build_dashboard(runner: "ExperimentRunner", pinned_at: Optional[float] = None) -> Dict[str, Any]:
    """
    The Grafana dashboard of a run: a summary, one panel per metric response and a marker per treatment

    It starts at the longest left window before the experiment start. Unless pinned_at is given, the dashboard is
    live: it refreshes itself and ends at now, or once the load ended, at the end of the longest right window.
    A pinned dashboard ends at pinned_at and does not refresh.
    """
    spec: ExperimentSpec = runner.config
    assert spec.experiment.services is not None, "Metric responses need experiment.services"
    assert runner.experiment_start is not None, "The dashboard of a run starts with its load"
    services = {service.target: service for service in spec.experiment.services.prometheus}
    left, _ = _windows(spec)
    live = pinned_at is None
    end = pinned_at if pinned_at is not None else observed_until(runner)
    time_range = {"from": _iso(runner.experiment_start - left), "to": "now" if end is None else _iso(end)}
    name = os.path.splitext(os.path.basename(runner.config_filename or "experiment"))[0]
    variant = runner.variant
    title = f"{name} · {variant.id} · {runner.short_id}" if variant.levels else f"{name} · {runner.short_id}"
    treatments = started_treatments(runner)
    panels: List[Dict[str, Any]] = [
        {
            "id": 1,
            "type": "text",
            "title": "Run",
            "gridPos": {"h": 4 + len(treatments), "w": 24, "x": 0, "y": 0},
            "options": {"mode": "markdown", "content": _summary(runner, treatments, live)},
        }
    ]
    y = panels[0]["gridPos"]["h"]
    for response in spec.experiment.responses:
        if not isinstance(response, MetricResponseDescription):
            continue
        datasource = {"type": "prometheus", "uid": datasource_uid(services[response.target])}
        panels.append(_metric_panel(response, datasource, panel_id=len(panels) + 1, y=y))
        y += 10
    # the markers only use time(), so any Prometheus does. The one of target oxn outlives the SUE and its Prometheus
    marker_service = services.get(MARKER_TARGET, spec.experiment.services.prometheus[0])
    marker_source = {"type": "prometheus", "uid": datasource_uid(marker_service)}
    return {
        "uid": dashboard_uid(runner.id),
        "title": title,
        "tags": ["oxn", name] + [f"{axis}={level}" for axis, level in variant.levels.items()],
        "timezone": "utc",
        "editable": False,
        "schemaVersion": 39,
        "time": time_range,
        "refresh": LIVE_REFRESH if live else "",
        "liveNow": False,
        "annotations": {"list": _markers(treatments, marker_source)},
        "panels": panels,
    }


def _labels(kind: str, run_id: Optional[str] = None) -> Dict[str, str]:
    labels = {"app.kubernetes.io/managed-by": "oxn", "oxn/kind": kind}
    if run_id is not None:
        labels["oxn/run"] = run_id[:8]
    return labels


class RunDashboard:
    """
    The live Grafana dashboard of one run, stored as ConfigMaps in the namespace of the spec's Grafana service

    The namespace matters: the datasource sidecar of kube-prometheus-stack only watches the namespace of Grafana.

    Reads the runner on every update, so it shows the treatments and timestamps as they are then. Failures are logged
    as warnings and never stop the run: the dashboard is for watching, the responses are still observed and stored as
    usual.
    """

    def __init__(self, orchestrator: "KubernetesOrchestrator", runner: "ExperimentRunner"):
        self.orchestrator = orchestrator
        self.kube_client: client.CoreV1Api = orchestrator.kube_client
        self.runner = runner
        self.namespace = ""
        """The namespace of Grafana, known after start()"""
        self.enabled = False
        """True once start() found Grafana. Without it, nothing is written, so the run is not slowed down by failed calls"""
        self.pinned_at: Optional[float] = None
        """The end of the time range once the dashboard is pinned, None while it is live"""

    @property
    def configmap_name(self) -> str:
        return f"oxn-dashboard-{self.runner.short_id}"

    @property
    def uid(self) -> str:
        return dashboard_uid(self.runner.id)

    def start(self) -> None:
        """Provision the datasources and publish the live dashboard"""
        try:
            grafana = self.orchestrator.get_grafana_service()
            self.kube_client.read_namespaced_service(grafana.name, grafana.namespace)
        except OrchestratorException as e:
            logger.warning(f"{e.message}, running without dashboard. {e.explanation}")
            return
        except ApiException as e:
            logger.warning(
                f"No Grafana service {grafana.name} in {grafana.namespace} ({e.status}), running without dashboard. "
                "Run oxn setup to install it"
            )
            return
        self.namespace = grafana.namespace
        self.enabled = True
        services = self.runner.config.experiment.services
        assert services is not None
        for service in services.prometheus:
            self._apply(
                name=f"oxn-datasource-{datasource_uid(service).removeprefix('oxn-prometheus-')}",
                labels={DATASOURCE_LABEL: "1", **_labels("datasource")},
                key="datasource.yaml",
                content=yaml.safe_dump(
                    build_datasource(
                        service, self.runner.orchestrator.get_prometheus_url(service.target, internal=True)
                    ),
                    sort_keys=False,
                ),
            )
        self.update()
        if self.enabled:
            logger.info(
                f"Live dashboard of run {self.runner.short_id}: kubectl port-forward -n {grafana.namespace} "
                f"svc/{grafana.name} 3000:{GRAFANA_PORT}, then open http://localhost:3000/d/{self.uid}"
            )

    def update(self) -> None:
        """Publish the dashboard again, with the run as it is now"""
        if not self.enabled:
            return
        self._apply(
            name=self.configmap_name,
            labels={DASHBOARD_LABEL: "1", **_labels("dashboard", self.runner.id)},
            key=f"{self.uid}.json",
            content=json.dumps(build_dashboard(self.runner, pinned_at=self.pinned_at), indent=1),
        )

    def finish(self) -> None:
        """
        Pin the dashboard and stop its refresh

        After a complete run, to the end of the observed window. If the run failed before its load ended, to now.
        """
        if self.pinned_at is not None:
            return
        until = observed_until(self.runner)
        self.pinned_at = until if until is not None else utc_timestamp()
        self.update()
        if self.enabled:
            logger.info(f"Pinned dashboard {self.uid} of run {self.runner.short_id}")

    def _apply(self, name: str, labels: Dict[str, str], key: str, content: str) -> None:
        if not self.enabled:
            return
        body = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=name, namespace=self.namespace, labels=labels),
            data={key: content},
        )
        try:
            try:
                self.kube_client.create_namespaced_config_map(namespace=self.namespace, body=body)
            except ApiException as e:
                if e.status != 409:
                    raise
                self.kube_client.replace_namespaced_config_map(name=name, namespace=self.namespace, body=body)
        except ApiException as e:
            logger.warning(f"Could not write ConfigMap {name} for the dashboard ({e.status} {e.reason}), proceeding")
