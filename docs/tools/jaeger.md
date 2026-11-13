# Jaeger

Jaeger stores the SUE's traces, and `oxn` reads them for trace responses.

| | |
|---|---|
| Chart | Subchart `jaeger` 4.13.1 of `open-telemetry/opentelemetry-demo`, which runs Jaeger v2 |
| Release and namespace | `astronomy-shop` in `system-under-evaluation` |
| Service | `jaeger`, port 16686 |
| Values | Under `jaeger:` in the demo's values files |

## Deploy with Helm

Jaeger has no separate install. It comes with the [OpenTelemetry Demo](opentelemetry-demo.md#deploy-with-helm), and the values file selects where it stores traces:

| Values file | Jaeger's memory limit | Traces are stored in |
|---|---|---|
| `values_opentelemetry_demo.yaml` | 5 GiB | Memory, lost when the pod restarts |
| `values_opentelemetry_demo_persistence.yaml` | 2 GiB | [Elasticsearch](elasticsearch.md) |

Both run as one `jaeger` deployment. Jaeger v2 no longer has separate collector and query deployments, and it reads its storage settings from `jaeger.userconfig` instead of `jaeger.storage`.

In-memory:

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm upgrade --install astronomy-shop open-telemetry/opentelemetry-demo \
    --namespace system-under-evaluation \
    --create-namespace \
    --version 0.42.6 \
    -f deployments/values/values_opentelemetry_demo.yaml
```

With Elasticsearch, which must be installed first:

```bash
helm upgrade --install astronomy-shop open-telemetry/opentelemetry-demo \
    --namespace system-under-evaluation \
    --create-namespace \
    --version 0.42.6 \
    -f deployments/values/values_opentelemetry_demo_persistence.yaml
```

The persistence values point Jaeger at `elasticsearch.system-under-evaluation.svc.cluster.local:9200`.

## Check it

```bash
kubectl get pods -n system-under-evaluation -l app.kubernetes.io/name=jaeger
kubectl port-forward -n system-under-evaluation svc/jaeger 16686:16686
```

Then open <http://localhost:16686>.

Specs find Jaeger through `services.jaeger` in the experiment spec, so keep the service name `jaeger`.

## Remove it

Jaeger is removed with the [OpenTelemetry Demo](opentelemetry-demo.md#remove-it) release. Traces in Elasticsearch stay until [Elasticsearch](elasticsearch.md#remove-it) and its volume are removed.
