# 11. Specs for the current stack

**Compared to GOXN:** every spec deploys its own stack, queries the metric names of the current charts and starts with a comment that says what it measures. The 30 s export specs no longer leave one service at 1 s. A new page explains the experiment design.

## Summary

In GOXN, the `recommendation_*` specs from the evaluation relied on `run_experiment_suite.sh` to install the SUE, and they queried the names of the old chart versions. [Stack versions](08-stack-versions.md) updated the charts and [A deployment section in the spec](03-deployment-section.md) removed the script, but both left these specs as they were (see the known limitations of [3](03-deployment-section.md#known-limitations) and [8](08-stack-versions.md#known-limitations)). This change brings all 23 of them, and `test.yml`, up to date. [Experiment design](../experiment-design.md) is a new page that explains what the specs compare.

| Area | GOXN | After this change |
|---|---|---|
| Deployment | No spec deploys anything, `run_experiment_suite.sh` installs the SUE | Every spec has a `deployment` section, in one of three setups |
| Jaeger service | `jaeger-query` | `jaeger` |
| Kepler responses | `kepler_container_{package,dram,other}_joules_total`, BPF IRQ counter | `kepler_pod_cpu_joules_total` and `kepler_container_cpu_joules_total` by `zone`. Six responses without a counterpart are dropped |
| Demo metrics | `http_client_duration_milliseconds_bucket`, `app_recommendations_counter_total` | `http_client_request_duration_seconds_bucket`, `demo_recommendation_requests_total` |
| 30 s export specs | `product-catalog` exports every 1 s | Every service exports every 30 s |
| Spec layout | Flow-style params, commented-out leftovers | Block style, a header comment in every spec |

## Deployment sections

**Now documented in:** [Deployments: shipped setups](../deployments.md#shipped-setups), [Elasticsearch](../tools/elasticsearch.md), [Istio](../tools/istio.md)

Each spec deploys one of three setups. None of them deploys Prometheus or Kepler, so run `oxn setup` first ([Getting started: prepare the cluster](../getting-started.md#prepare-the-cluster)).

| Setup | Specs | Deploys |
|---|---|---|
| In-memory Jaeger | `test.yml`, `recommendation_*` without `persistence` in the name | The SUE with `values_opentelemetry_demo.yaml` |
| Elasticsearch | `recommendation_*_persistence*` | `k8s/elasticsearch/`, waiting for `deployment/elasticsearch`, then the SUE with `values_opentelemetry_demo_persistence.yaml` |
| Istio | `recommendation_k8_base_1m_otel_persistence_istio.yml` | Istio 1.30.7 in `istio-system`, sidecar injection on `system-under-evaluation`, then the Elasticsearch setup |

The Istio spec differs from GOXN's suite in two ways:

- **Gateway service.** The ingress gateway's service is a `ClusterIP`. `helm --wait` would otherwise wait for a LoadBalancer IP, and the load does not go through the gateway.
- **Shared Prometheus.** The old suite also upgraded kube-prometheus with `values_kube_prometheus_istio.yaml`, to scrape the sidecars. No response reads those metrics, so the spec leaves the shared Prometheus alone.

**Why.** The SUE for these specs was installed by `run_experiment_suite.sh`, which [A deployment section in the spec](03-deployment-section.md) replaced with the `deployment` section. Without one, the specs could only run against a stack someone had set up by hand.

## Metric names

**Now documented in:** [Kepler: metrics](../tools/kepler.md#metrics), [Experiment design: responses](../experiment-design.md#responses)

### Kepler

Kepler 0.12 reports energy per RAPL `zone` instead of one metric per component:

| GOXN | Now |
|---|---|
| `kepler_container_package_joules_total` | `kepler_*_cpu_joules_total{zone="package"}` |
| `kepler_container_dram_joules_total` | `kepler_*_cpu_joules_total{zone="dram"}` |
| `kepler_container_joules_total` | `kepler_*_cpu_joules_total{zone=~"package\|dram"}` |

Namespace-level and pod-level responses use `kepler_pod_cpu_joules_total`. Per-container responses use `kepler_container_cpu_joules_total`, joined to the pod metric on `pod_id` to get the namespace. The queries rename `pod_namespace` to `container_namespace` with `label_replace`, so the responses keep the labels that the evaluation code reads.

These responses were dropped from the 20 specs that had them, because Kepler 0.12 exports no counterpart:

- `recommendation_kepler_other_joules`, `pods_kepler_other_joules_all`, `pods_kepler_other_joules_all_absolute`, `kepler_other_joules_namespace_combined` and `kepler_other_joules_namespace_combined_absolute`. Kepler 0.12 has no `other` energy zone.
- `kepler_network_packages_received`. It read the BPF counter `kepler_container_bpf_net_rx_irq_total`.

### OpenTelemetry Demo

| GOXN | Now |
|---|---|
| `http_client_duration_milliseconds_bucket` | `http_client_request_duration_seconds_bucket` |
| `app_recommendations_counter_total` | `demo_recommendation_requests_total` |

The frontend latency is now in seconds, not milliseconds. Keep this in mind when you compare the p95 latency with GOXN results.

[Stack versions](08-stack-versions.md#experimentstestyml) had switched `test.yml` to the server-side `http_server_request_duration_seconds_bucket`. It now uses the client-side metric as well, so all specs measure the same latency.

## Fix in the 30 s export specs

**Now documented in:** [Experiment design: metric export interval](../experiment-design.md#metric-export-interval)

`recommendation_k8_base_30s_otel.yml` and `recommendation_k8_base_30s_otel_persistence.yml` set the metric export interval of every service to 30 s, except `product-catalog`, which was set to 1 s. It is 30 s now.

GOXN results from these two specs were recorded with `product-catalog` exporting every second.

## Spec layout

**Now documented in:** [Experiments: spec structure](../experiments.md#spec-structure)

- **Header comment.** Every spec starts with a comment that names the SUE setup, the treatments before and during the load, the load and the responses.
- **Block style.** Treatment params, Prometheus services, `required` and `locust_files` are written in YAML block style instead of flow style with trailing commas.
- **Leftovers removed.** Commented-out responses and treatments, such as an old `sampling_rates` response and earlier `delay_treatment` drafts, are gone. `test.yml` keeps its commented-out examples of the other treatment types on purpose.

## Documentation

- [Experiment design](../experiment-design.md) is new. It explains what the experiments compare, how a run is timed and which specs to compare with each other.
- [Deployments](../deployments.md#shipped-setups) lists the three setups instead of `test.yml` and the removed `debug.yml`. [Istio](../tools/istio.md) points to the Istio spec.
- **Mermaid diagrams.** The docs load `sphinxcontrib-mermaid`, so plain `mermaid` code fences render as diagrams on the site and on GitHub.
- **Live preview.** `make docs-serve` rebuilds the site on every change and opens it in the browser, using `sphinx-autobuild`. `DOCS_PORT` sets the port, default 8000.

## Known limitations

- **Storage device.** The storage responses filter on the device `/dev/md2`, the disk of the ISE cluster node, as in GOXN. On another cluster they return no data until you change the device.
- **Shared monitoring.** Prometheus and Kepler stay on the cluster between runs, so their versions are not part of what a spec records. `oxn setup` pins them ([Getting started: prepare the cluster](../getting-started.md#prepare-the-cluster)).
