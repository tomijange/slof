# OpenTelemetry Demo

The OpenTelemetry Demo, also called the Astronomy Shop, is the system under experiment (SUE). Its chart also installs the [collector](opentelemetry-collector.md), [Jaeger](jaeger.md), a second Prometheus, a second Grafana and OpenSearch.

| | |
|---|---|
| Chart | `open-telemetry/opentelemetry-demo` |
| Version | 0.42.6, which runs demo version 3.1.0 |
| Release and namespace | `astronomy-shop` in `system-under-evaluation` |
| Installed by | The `deployment` section of `experiments/test.yml` and `experiments/debug.yml`, or the commands below |

**This chart cannot be upgraded in place.** To move to another version, remove the release first. See [Remove it](#remove-it).

## Deploy with Helm

Pick the values file for your setup:

| Setup | Values file | Requires first |
|---|---|---|
| In-memory Jaeger | `values_opentelemetry_demo.yaml` | [OpenEBS](openebs.md) |
| Persistence | `values_opentelemetry_demo_persistence.yaml` | [OpenEBS](openebs.md), [Elasticsearch](elasticsearch.md) |
| Persistence in Istio | `values_opentelemetry_demo_persistence.yaml` | The above, plus [Istio](istio.md) |

For in-memory Jaeger:

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm upgrade --install astronomy-shop open-telemetry/opentelemetry-demo \
    --namespace system-under-evaluation \
    --create-namespace \
    --version 0.42.6 \
    -f deployments/values/values_opentelemetry_demo.yaml
```

For persistence:

```bash
helm upgrade --install astronomy-shop open-telemetry/opentelemetry-demo \
    --namespace system-under-evaluation \
    --create-namespace \
    --version 0.42.6 \
    -f deployments/values/values_opentelemetry_demo_persistence.yaml
```

On a small local cluster, add the overlay as a second values file:

```bash
helm upgrade --install astronomy-shop open-telemetry/opentelemetry-demo \
    --namespace system-under-evaluation \
    --create-namespace \
    --version 0.42.6 \
    -f deployments/values/values_opentelemetry_demo_persistence.yaml \
    -f deployments/values/values_opentelemetry_demo_local.yaml
```

The values files disable two groups of components:

- The chart's built-in load generator, because `oxn` generates the load with [Locust](locust.md).
- The `agent`, `chatbot`, `mcp` and `telemetry-docs` components that demo 3.x added. The AI components need an LLM backend, and the load that the specs generate does not use any of them.

## Check it

```bash
kubectl get pods -n system-under-evaluation
kubectl port-forward -n system-under-evaluation svc/frontend-proxy 8080:8080
```

Then open the shop at <http://localhost:8080>.

## Remove it

```bash
helm uninstall astronomy-shop --namespace system-under-evaluation
kubectl delete pvc --namespace system-under-evaluation -l app.kubernetes.io/instance=astronomy-shop
```

Helm keeps PVCs created by StatefulSets, so the second command removes them.
