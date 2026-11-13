# Grafana

Grafana shows dashboards for the external Prometheus, including GOXN's Kepler dashboard. `oxn` does not need it to run experiments.

| | |
|---|---|
| Chart | Part of `prometheus-community/kube-prometheus-stack` |
| Version | 92.16.1 |
| Release and namespace | `kube-prometheus` in `oxn-external-monitoring` |
| Service | `kube-prometheus-grafana`, port 80 |
| Login | `admin` / `admin`, set in `values_kube_prometheus.yaml` |

## Deploy with Helm

Grafana has no separate install. It comes with the [Prometheus](prometheus.md#deploy-with-helm) command:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
    --namespace oxn-external-monitoring \
    --create-namespace \
    --version 92.16.1 \
    -f deployments/values/values_kube_prometheus.yaml
```

The password is for a cluster-internal test setup. Change it if the service is exposed.

## Add the Kepler dashboard

Store the dashboard in a labelled ConfigMap, and Grafana's sidecar loads it automatically:

```bash
kubectl create configmap kepler-dashboard \
    --namespace oxn-external-monitoring \
    --from-file=deployments/dashboards/kepler_dashboard.json
kubectl label configmap kepler-dashboard \
    --namespace oxn-external-monitoring \
    grafana_dashboard=1
```

Unlike a file copied into the pod, the ConfigMap survives pod restarts and the removal of the `kube-prometheus` release between experiments.

## Check it

```bash
kubectl port-forward -n oxn-external-monitoring svc/kube-prometheus-grafana 3000:80
```

Then open <http://localhost:3000>.

## Remove it

Grafana is removed together with the [Prometheus](prometheus.md#remove-it) release. The dashboard ConfigMap needs its own command:

```bash
kubectl delete configmap kepler-dashboard --namespace oxn-external-monitoring
```

## The second Grafana

The [OpenTelemetry Demo](opentelemetry-demo.md) chart also installs a Grafana, the service `grafana` in `system-under-evaluation`. It shows the SUE's own telemetry and is separate from this one.
