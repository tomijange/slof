# Istio

Istio adds a service mesh around the SUE, so that experiments can measure what a mesh costs. No shipped spec deploys it.

| Release | Chart | Version | Namespace | Values |
|---|---|---|---|---|
| `istio-base` | `istio/base` | 1.30.7 | `istio-system` | `--set defaultRevision=default` |
| `istiod` | `istio/istiod` | 1.30.7 | `istio-system` | `deployments/values/values_istiod.yaml` |
| `istio-ingressgateway` | `istio/gateway` | 1.30.7 | `istio-system` | Chart defaults |

To deploy it with an experiment, add these releases to the spec's `deployment` section.

## Deploy with Helm

Install Istio after [Prometheus](prometheus.md), using `values_kube_prometheus_istio.yaml` so that Prometheus scrapes the mesh.

```bash
helm repo add istio https://istio-release.storage.googleapis.com/charts
helm repo update

helm upgrade --install istio-base istio/base \
    --namespace istio-system \
    --create-namespace \
    --version 1.30.7 \
    --set defaultRevision=default

helm upgrade --install istiod istio/istiod \
    --namespace istio-system \
    --version 1.30.7 \
    -f deployments/values/values_istiod.yaml

helm upgrade --install istio-ingressgateway istio/gateway \
    --namespace istio-system \
    --version 1.30.7
```

Then enable sidecar injection before installing the [SUE](opentelemetry-demo.md). The pods only get sidecars if the label is in place when they start:

```bash
kubectl create namespace system-under-evaluation
kubectl label namespace system-under-evaluation istio-injection=enabled --overwrite
```

Skip the `create namespace` command if the namespace exists.

`values_istiod.yaml` sends the mesh's traces to the SUE's collector at `otel-collector.system-under-evaluation.svc.cluster.local:9411`.

## Check it

```bash
kubectl get pods -n istio-system
kubectl get pods -n system-under-evaluation -o jsonpath='{.items[0].spec.containers[*].name}'
```

The second command should list `istio-proxy` among the containers.

## Remove it

```bash
helm uninstall istio-ingressgateway --namespace istio-system
helm uninstall istiod --namespace istio-system
helm uninstall istio-base --namespace istio-system
kubectl delete namespace istio-system
```
