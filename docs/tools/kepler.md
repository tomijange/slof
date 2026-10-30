# Kepler

Kepler estimates energy use per pod and container and exports it as Prometheus metrics. The energy responses in the experiment specs read these metrics, such as `kepler_pod_cpu_joules_total`.

| | |
|---|---|
| Chart | `oci://quay.io/sustainable_computing_io/charts/kepler` |
| Version | 0.12.0, which runs Kepler `v0.12.0` |
| Release and namespace | `kepler` in `oxn-external-monitoring` |
| Values | `deployments/values/values_kepler.yaml` |
| Service | `kepler`, port 28282 |
| Installed by | `oxn setup`, once per cluster |

Kepler needs real hardware energy counters and runs privileged on every node.

## Deploy with Helm

[Prometheus](prometheus.md) must be installed first, because this chart creates a `ServiceMonitor`.

The chart is published to an OCI registry, so there is no repository to add:

```bash
helm upgrade --install kepler oci://quay.io/sustainable_computing_io/charts/kepler \
    --namespace oxn-external-monitoring \
    --create-namespace \
    --version 0.12.0 \
    -f deployments/values/values_kepler.yaml
```

The values file does three things:

- It labels the `ServiceMonitor` with `release: kube-prometheus`, so that Prometheus scrapes Kepler. The chart disables the `ServiceMonitor` by default.
- It sets the scrape interval to 30s. The chart's default is 5s, and every scrape triggers a power computation.
- It lowers the log level from the chart's default of `debug` to `info`.

The old chart at `sustainable-computing-io.github.io/kepler-helm-chart` is deprecated. It stops at 0.6.2, which runs Kepler `release-0.8.0`.

## Metrics

Kepler 0.10 replaced its metric schema, so results from older Kepler versions are not directly comparable with new ones. It also dropped the eBPF and model-based estimation of the old versions, and it attributes measured RAPL energy using CPU time instead.

| Old metric | New metric |
|---|---|
| `kepler_container_package_joules_total` | `kepler_pod_cpu_joules_total{zone="package"}` |
| `kepler_container_dram_joules_total` | `kepler_pod_cpu_joules_total{zone="dram"}` |
| `kepler_container_joules_total` | `kepler_pod_cpu_joules_total{zone=~"package\|dram"}` |
| `kepler_container_gpu_joules_total` | `kepler_pod_gpu_joules_total` |
| `kepler_container_other_joules_total` | None, removed from the specs |
| `kepler_container_bpf_net_rx_irq_total` | None, removed from the specs |

The labels changed too:

| Old label | New label |
|---|---|
| `container_namespace` | `pod_namespace`, only on `kepler_pod_*` |
| `pod_name` | `pod_name`, only on `kepler_pod_*` |
| `node` | `node_name` |

`kepler_container_cpu_joules_total` only has `pod_id`, `container_id` and `container_name`. For a per-container result with a namespace, join it to the pod metric:

```promql
sum by (container_name, pod_namespace) (
  rate(kepler_container_cpu_joules_total{zone="package"}[90s])
  * on(pod_id) group_left(pod_namespace)
  group by (pod_id, pod_namespace) (kepler_pod_cpu_joules_total{pod_namespace="system-under-evaluation"})
)
```

**Do not sum all zones.** They overlap: `package` already contains `core` and `uncore`. The specs add `package` and `dram` only, which do not overlap.

Which zones exist depends on the CPU and kernel. Check that `dram` is available on a new cluster, because responses that select it stay empty otherwise.

## Check it

```bash
kubectl get pods -n oxn-external-monitoring -l app.kubernetes.io/name=kepler
kubectl port-forward -n oxn-external-monitoring svc/kepler 28282:28282
```

Then look for energy metrics at <http://localhost:28282/metrics>.

## Remove it

```bash
helm uninstall kepler --namespace oxn-external-monitoring
```
