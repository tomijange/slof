# GOXN documentation

Start with [Getting started](getting-started.md) if you are setting up GOXN for the first time.

| Guide                                 | Covers                                                                         |
| ------------------------------------- | ------------------------------------------------------------------------------ |
| [Getting started](getting-started.md) | Installing `oxn`, preparing a cluster, running a first experiment              |
| [Deployments](deployments.md)         | The `deployment` section of a spec, deploying and tearing down the stack       |
| [Experiments](experiments.md)         | Experiment specs, treatments, the `oxn` command, reports                       |
| [Architecture](architecture.md)       | How the `oxn` modules work together during a run                               |

## Tools

Every tool has a page with its Helm command, its values, how to check it and how to remove it.

| Tool                                                        | Role                                           | Helm chart                                                                           | Version         | Namespace                 |
| ----------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------ | --------------- | ------------------------- |
| [OpenEBS](tools/openebs.md)                                 | Storage for persistent volumes                 | `openebs/openebs`                                                                    | 4.6.2           | `openebs`                 |
| [Prometheus](tools/prometheus.md)                           | Metrics that `oxn` reads as experiment results | `prometheus-community/kube-prometheus-stack`                                         | 92.16.1         | `oxn-external-monitoring` |
| [Grafana](tools/grafana.md)                                 | Dashboards                                     | part of `kube-prometheus-stack`                                                      | 92.16.1         | `oxn-external-monitoring` |
| [Kepler](tools/kepler.md)                                   | Energy metrics                                 | `oci://quay.io/sustainable_computing_io/charts/kepler`                               | 0.12.0          | `oxn-external-monitoring` |
| [OpenTelemetry Demo](tools/opentelemetry-demo.md)           | The system under experiment (SUE)              | `open-telemetry/opentelemetry-demo`                                                  | 0.42.6          | `system-under-evaluation` |
| [OpenTelemetry Collector](tools/opentelemetry-collector.md) | Receives and samples telemetry                 | part of `opentelemetry-demo`                                                         | 0.42.6          | `system-under-evaluation` |
| [Jaeger](tools/jaeger.md)                                   | Traces                                         | part of `opentelemetry-demo`                                                         | 0.42.6          | `system-under-evaluation` |
| [Elasticsearch](tools/elasticsearch.md)                     | Trace storage for the persistence setups       | `elastic/elasticsearch` and `prometheus-community/prometheus-elasticsearch-exporter` | 8.5.1 and 7.4.1 | `system-under-evaluation` |
| [Istio](tools/istio.md)                                     | Service mesh for the Istio experiment          | `istio/base`, `istio/istiod`, `istio/gateway`                                        | 1.30.7          | `istio-system`            |
| [Locust](tools/locust.md)                                   | Load generation                                | `deliveryhero/locust` (manual use only)                                              | 0.31.6          | `system-under-evaluation` |

Two of these are normally not installed from the chart listed:

- **Elasticsearch** comes from the manifests in `k8s/elasticsearch/` in all persistence specs.
- **Locust** is created and removed by `oxn` during each run.

Their pages explain both routes.

## Install order

`oxn setup` installs OpenEBS, Prometheus and Kepler in the right order. The experiment specs take care of the rest. If you install by hand, the order matters, because later tools depend on earlier ones:

1. **OpenEBS.** The charts and manifests request the `openebs-hostpath` StorageClass.
2. **Prometheus.** It installs the `ServiceMonitor` CRD that Kepler and the Elasticsearch manifests need.
3. **Kepler.**
4. **Istio**, only for the Istio experiment. Label the SUE namespace before installing the SUE.
5. **Elasticsearch**, only for the persistence setups. Jaeger needs it at startup.
6. **OpenTelemetry Demo.**

OpenEBS and Kepler are cluster infrastructure: install them once. `oxn` deploys and removes everything else for each run, as described in [Deployments](deployments.md).
