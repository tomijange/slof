# OpenTelemetry Collector

The collector receives traces and metrics from the SUE's services. It samples the traces and forwards the telemetry to [Jaeger](jaeger.md) and the SUE's Prometheus.

| | |
|---|---|
| Chart | Subchart `opentelemetry-collector` 0.173.1 of `open-telemetry/opentelemetry-demo` |
| Release and namespace | `astronomy-shop` in `system-under-evaluation` |
| Service | `otel-collector` |
| Values | Under `opentelemetry-collector:` in the demo's values files |

The chart's default is a DaemonSet with host, kubelet and cluster metrics. The values files switch back to a single Deployment without those metrics, because the `kube_probl` treatment expects a Deployment and the ConfigMap `otel-collector`.

## Deploy with Helm

The collector has no separate install. It comes with the [OpenTelemetry Demo](opentelemetry-demo.md#deploy-with-helm):

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm upgrade --install astronomy-shop open-telemetry/opentelemetry-demo \
    --namespace system-under-evaluation \
    --create-namespace \
    --version 0.42.6 \
    -f deployments/values/values_opentelemetry_demo_persistence.yaml
```

## Sampling configuration

Both values files add a `probabilistic_sampler` to the trace pipeline, with a fixed `hash_seed` of 22 and a default of 1%:

```yaml
opentelemetry-collector:
  config:
    processors:
      probabilistic_sampler:
        sampling_percentage: 1
        hash_seed: 22
```

The `kube_probl` treatment changes the rate during an experiment. See [Treatments](../experiments.md#treatments).

## Check it

```bash
kubectl get pods -n system-under-evaluation -l app.kubernetes.io/name=opentelemetry-collector
kubectl logs -n system-under-evaluation deployment/otel-collector
```

## Remove it

The collector is removed with the [OpenTelemetry Demo](opentelemetry-demo.md#remove-it) release.
