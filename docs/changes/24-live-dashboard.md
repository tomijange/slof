# 24. Live dashboard

**Compared to GOXN:** with `--dashboard`, every run shows its metric responses live in a Grafana dashboard that `oxn` builds from the spec, with a band per treatment. When the run ends, the dashboard is pinned to the observed window and kept as a record of the run.

## Summary

In GOXN, the responses of a run are only visible after it ends, in `store.h5` and the report. A run of 70 minutes gives no sign whether its queries return data, or whether a treatment shows an effect, until it is over. This change adds `--dashboard`: `oxn` writes one Grafana dashboard per run, with one panel per metric response, and the Grafana of kube-prometheus-stack shows it live.

| | GOXN | After this change |
|---|---|---|
| Responses during a run | Not visible | One panel per metric response, refreshed every 10 s, with `--dashboard` |
| Treatments during a run | In the log | A band per treatment on every panel, and a table with start and end |
| After the run | `store.h5` and the report | Also a dashboard pinned to the observed window, tagged with the spec and variant |
| Grafana datasources | Only the external Prometheus | One per Prometheus in `services.prometheus`, written by `oxn` |

## The dashboard

**Now documented in:** [Experiments](../experiments.md#live-dashboard)

`build_dashboard` in `oxn/observability/dashboard.py` turns the `ExperimentRunner` of a run into Grafana dashboard JSON. It reads the spec, variant, run id, experiment start and end and the treatments from the runner, so the dashboard has no model of its own:

| Part | Built from |
|---|---|
| Run panel | Spec path, run id, variant levels, start and end, the treatments that started so far, the names of trace responses |
| Metric panels | `metric_name` and `labels` of a metric response through `Prometheus.build_query`, so the panel queries what `oxn` stores. The datasource of its `target`, its `step` as the minimum interval |
| Treatment markers | A Prometheus annotation query per treatment, `vector(time()) > <start> < <end>`. It has a sample at every step while the treatment runs, which Grafana draws as one band. An open treatment has no upper bound, so its band grows. They query the Prometheus of target `oxn`, the first one if the spec has none |
| Time range | From the longest `left_window` before the start. To now during the load, then to the longest `right_window` after its end |
| uid, title, tags | `oxn-run-<run id>`, `<spec> · <variant> · <run>`, `oxn`, the spec name and every `axis=level` |

**Why.** A long run that records nothing useful is only noticed afterwards. Seeing the responses live shows a broken query in the first minutes, and the bands show whether a treatment changes them. Responses are already PromQL with a step, so a panel per response is close to a copy of the spec. Grafana is already part of kube-prometheus-stack, and a page served by `oxn` would have to rebuild its charts and stop with `oxn`. Markers from PromQL need no Grafana login, unlike annotations through its HTTP API.

## Publishing it

**Now documented in:** [Grafana](../tools/grafana.md#dashboards-and-datasources-from-oxn), [Architecture](../architecture.md#one-experiment-run)

`RunDashboard` holds the runner and stores the dashboard and the datasources as ConfigMaps in the namespace of the spec's `services.grafana`, which `KubernetesOrchestrator.get_grafana_service` returns, through the `CoreV1Api` client of the orchestrator. Every shipped spec names `kube-prometheus-grafana` in `oxn-external-monitoring`, the Grafana of `oxn setup`. The sidecars of the chart watch for the labels `grafana_dashboard=1` and `grafana_datasource=1` and reload Grafana, so `oxn` needs no Grafana credentials and no port-forward. An existing ConfigMap is replaced.

| When | What the engine does |
|---|---|
| The load started | Checks that the `kube-prometheus-grafana` service exists, writes the datasources and the live dashboard, logs the port-forward command and URL |
| A runtime treatment starts or ends | Writes the dashboard again. `ExperimentRunner.execute_runtime_treatments` takes an `on_change` callback for this |
| The load ended | Writes it again, with the compile-time treatments ended and the time range to the end of the right window |
| The responses are observed | Pins it to the observed window and turns off the refresh |
| `Engine.teardown` of a failed or interrupted run | Pins it to the end of the right window if the load ended, else to the time of the teardown |

The uid of a datasource is derived from the namespace and name of its Prometheus, not from the target, so a dashboard keeps reading from the same Prometheus even if a later spec gives its target to another one. Datasources go to the namespace of Grafana because the datasource sidecar only watches that namespace.

Without Grafana, `oxn` logs a warning and writes nothing more for that run. A failed write is a warning too. The dashboard never stops a run.

**Why.** Labelled ConfigMaps are how [Grafana](../tools/grafana.md#add-the-kepler-dashboard) already loads the Kepler dashboard, and they survive restarts of the Grafana pod. Writing them from the spec instead of adding datasources to `values_kube_prometheus.yaml` keeps specs that name other Prometheus instances working without a new `oxn setup`.

**What this breaks.** Nothing. Without `--dashboard`, a run writes nothing to Grafana.

## Tests

`oxn/tests/unit/test_dashboard.py` checks the time range of a live and a pinned dashboard, the panel per metric response with its datasource, query and interval, the Run panel, the markers and their datasource, that only started treatments are shown, the ConfigMaps and their labels, replacing an existing ConfigMap, a run without Grafana, a failed write, that pinning happens once, the `on_change` callback of the runner, that the engine starts, updates and pins the dashboard and pins it at teardown after a failure, and that `--dashboard` is off by default. `python -m pytest oxn/tests/unit` reports 245 passing tests and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists.

The dashboard was also checked against the Grafana 13.3 of kube-prometheus-stack 92.16.1 on the cluster, with the responses of `recommendation_k8_minimal`. Grafana loaded the datasources and the dashboard from the ConfigMaps, its metric queries returned without errors, and the markers covered the treatment windows, live and after pinning.

## Known limitations

| Limitation | Status |
|---|---|
| Panels of a Prometheus inside the SUE, target `sue` in the shipped specs, are empty after the teardown, because its data goes with the SUE. | By design |
| Trace responses are listed, not plotted. | Open |
| `oxn` does not remove the dashboards. `kubectl delete configmap -n oxn-external-monitoring -l app.kubernetes.io/managed-by=oxn,oxn/kind=dashboard` does. | Open |
| The datasource sidecar may take a few seconds to load a new datasource, so the first refresh of a new dashboard can show errors. | Open |
