# 8. Stack versions

**Compared to GOXN:** the observability stack and the SUE run on current chart and image versions, and `experiments/test.yml` uses their metric and service names.

## Summary

The chart versions GOXN pinned no longer matched current Kubernetes and Kepler releases. This change updates the charts and images, and adapts the values files, manifests and `experiments/test.yml` to the names that changed with them.

| Component | GOXN | After this change |
|---|---|---|
| kube-prometheus-stack | 62.5.1 | 92.16.1 |
| OpenTelemetry Demo | 0.36.4 | 0.42.6 (demo 3.x) |
| Kepler | `kepler/kepler` from the old Helm repo | `oci://quay.io/sustainable_computing_io/charts/kepler` 0.12.0 |
| OpenEBS | `openebs-operator.yaml` manifest | Helm chart 4.6.2 |
| Istio | 1.26.2, in `run_experiment_suite.sh` | 1.30.7, in the [Istio](../tools/istio.md) page. No spec deploys it yet |
| Elasticsearch and Kibana images | 8.13.4 | 8.19.23 |
| Elasticsearch exporter image | v1.6.0 | v1.11.0 |

**Why.** The fork should measure a current stack. Pinning the versions in the spec's `deployment` section, from [A deployment section in the spec](03-deployment-section.md), makes them part of what an experiment records.

## OpenTelemetry Demo

**Now documented in:** [OpenTelemetry Demo](../tools/opentelemetry-demo.md), [OpenTelemetry Collector](../tools/opentelemetry-collector.md), [Jaeger](../tools/jaeger.md)

What the update changed in `deployments/values/values_opentelemetry_demo*.yaml`:

- **Jaeger v2.** The service is now called `jaeger`, not `jaeger-query`. Resources are set under `jaeger.jaeger` instead of `jaeger.allInOne`. The Elasticsearch persistence setup is written as collector-style `userconfig` (`jaeger_storage`, `jaeger_query`), because the old `storage:` values no longer exist.
- **Collector mode.** The OpenTelemetry Collector is set back to `mode: deployment` with the new presets turned off. The `kube_probl` treatment expects a Deployment with the ConfigMap `otel-collector`. The new chart defaults to a DaemonSet that also collects host, kubelet and cluster metrics, which 0.36.4 did not do.
- **Trace pipeline.** The trace pipeline lists the processors of the new chart, with `probabilistic_sampler` added at the end.
- **AI add-ons.** `agent`, `chatbot`, `mcp` and `telemetry-docs` are turned off. They need an LLM backend and are not part of the load the specs generate.
- **Memory limits.** In the default values, `ad` and `fraud-detection` get 1 GiB, and the limits for `flagd`, `product-catalog`, `checkout`, `frontend-proxy` and `email` are commented out. The OpenTelemetry Collector limit drops from 18 GiB to 8 GiB. The persistence values keep the GOXN limits.

## Small clusters

**Now documented in:** [Deployments: small clusters](../deployments.md#small-clusters)

`values_opentelemetry_demo_local.yaml` is a new overlay that shrinks memory so the SUE fits into about 8 GB, for example on a laptop cluster. Add it to the `values` of the `astronomy-shop` release. Do not report numbers from runs that use it.

## Kepler

**Now documented in:** [Kepler: metrics](../tools/kepler.md#metrics)

The new chart exports different metrics. The old `extraEnvVars` settings in `values_kepler.yaml` no longer apply, so the values now only set the log level and the `ServiceMonitor` (30 s interval, label `release: kube-prometheus`).

| GOXN metric | After this change |
|---|---|
| `kepler_container_package_joules_total` | `kepler_pod_cpu_joules_total{zone="package"}` |
| `kepler_container_dram_joules_total` | `kepler_pod_cpu_joules_total{zone="dram"}` |
| `kepler_container_joules_total` | `kepler_container_cpu_joules_total{zone=~"package\|dram"}`, joined with the pod metric for namespace and pod name |
| `kepler_container_other_joules_total`, `kepler_container_bpf_net_rx_irq_total` | No replacement. The responses that used them were removed from `test.yml` |

Labels changed too: `container_namespace` is now `pod_namespace`, and `node` is now `node_name`.

## Elasticsearch and Prometheus manifests

**Now documented in:** [Elasticsearch](../tools/elasticsearch.md), [Prometheus](../tools/prometheus.md)

- The chart labels in `k8s/elasticsearch/ServiceMonitor.yaml` match kube-prometheus-stack 92.16.1, so Prometheus selects it.
- Elasticsearch has a readiness probe that waits for cluster health `yellow`. A `wait_for: [deployment/elasticsearch]` step then only finishes once Elasticsearch accepts requests, which Jaeger needs at startup.

## `experiments/test.yml`

**Now documented in:** [Experiments: spec structure](../experiments.md#spec-structure)

`test.yml` is the spec kept in step with the new versions:

- It has a `deployment` section for the OpenTelemetry Demo 0.42.6.
- Jaeger is `jaeger` instead of `jaeger-query`.
- The Kepler responses use the metrics in the table above.
- The demo's metric names changed:

  | GOXN | After this change |
  |---|---|
  | `http_client_duration_milliseconds_bucket` (90 s rate) | `http_server_request_duration_seconds_bucket` (2 m rate) |
  | `app_recommendations_counter_total` | `demo_recommendation_requests_total` |
  | `otelcol_processor_probabilistic_sampler_count_traces_sampled` | `otelcol_processor_probabilistic_sampler_count_traces_sampled_total` |

- The cAdvisor network response reads `container_network_transmit_bytes_total` from the kubelet with the `pod` and `namespace` labels. The GOXN query had two label selectors and could not run.
- The delay treatment lasts 1 minute instead of 60.

**What this breaks.** Queries, dashboards and evaluation code that use the old Kepler or demo metric names return nothing against this stack. With [the previous change](06-skip-missing-responses.md), such a response is skipped with a warning.

## Known limitations

| Limitation | Status |
|---|---|
| **Outdated specs.** The `recommendation_*` specs still use the old service and metric names, such as `jaeger-query` and the old Kepler metrics. `experiments/test.yml` is the only spec kept up to date. | Open |
