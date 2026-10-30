# Prometheus

Prometheus stores the metrics that `oxn` reads as experiment results. GOXN uses the kube-prometheus-stack chart, which also installs [Grafana](grafana.md), the Prometheus Operator, kube-state-metrics and node-exporter.

| | |
|---|---|
| Chart | `prometheus-community/kube-prometheus-stack` |
| Version | 92.16.1 |
| Release and namespace | `kube-prometheus` in `oxn-external-monitoring` |
| Values | `deployments/values/values_kube_prometheus.yaml` |
| Installed by | `oxn setup`, the `deployment` section of `experiments/debug.yml`, or the command below |

## Deploy with Helm

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
    --namespace oxn-external-monitoring \
    --create-namespace \
    --version 92.16.1 \
    -f deployments/values/values_kube_prometheus.yaml
```

For the Istio setup, use `deployments/values/values_kube_prometheus_istio.yaml` instead. It adds scrape jobs for the Envoy sidecars, istiod and the ingress gateway.

Helm installs CRDs but never updates them, and teardown leaves them in place. On a cluster that already has CRDs from an older chart, update them before you deploy:

```bash
kubectl apply --server-side --force-conflicts \
    -f https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.94.2/stripped-down-crds.yaml
```

**Keep the release name `kube-prometheus`.** Other parts of GOXN rely on names derived from it:

- Specs query the service `kube-prometheus-kube-prome-prometheus` and filter on `service="kube-prometheus-kube-prome-kubelet"`.
- Prometheus only picks up a `ServiceMonitor` labelled `release: kube-prometheus`.

The values file adds pod and namespace labels to kube-state-metrics, which the specs use to group metrics by service.

## Check it

```bash
kubectl get pods -n oxn-external-monitoring
kubectl port-forward -n oxn-external-monitoring svc/kube-prometheus-kube-prome-prometheus 9090:9090
```

Then open <http://localhost:9090/targets>.

## Remove it

```bash
helm uninstall kube-prometheus --namespace oxn-external-monitoring
```

Helm leaves the CRDs in place, including `ServiceMonitor`, so Kepler's `ServiceMonitor` survives.

## The second Prometheus

The [OpenTelemetry Demo](opentelemetry-demo.md) chart installs its own Prometheus, the service `prometheus` in `system-under-evaluation`. Specs select between the two with `target`:

| `target` | Prometheus | Holds |
|---|---|---|
| `oxn` | `kube-prometheus-kube-prome-prometheus` | Cluster, cAdvisor and Kepler metrics |
| `sue` | `prometheus` | Metrics from the SUE's collector |
