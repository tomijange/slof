# Elasticsearch

In the persistence setups, Elasticsearch stores [Jaeger](jaeger.md)'s traces, so that storage cost shows up in experiment results. An exporter makes its metrics available to [Prometheus](prometheus.md).

| | Manifests (used by `oxn`) | Helm (manual alternative) |
|---|---|---|
| Source | `k8s/elasticsearch/` | `elastic/elasticsearch` 8.5.1 and `prometheus-community/prometheus-elasticsearch-exporter` 7.4.1 |
| Elasticsearch version | 8.19.23 | 8.19.23, set with `imageTag` |
| Exporter version | 1.11.0 | 1.11.0, the chart's default |
| Workload | Deployment | StatefulSet |
| Service | `elasticsearch`, port 9200 | `elasticsearch`, port 9200 |
| Namespace | `system-under-evaluation` | `system-under-evaluation` |

Use only one of the two routes in a namespace. Both create the same service.

## Deploy with Helm

This route is an alternative to what the specs' `deployment` sections do, and no reported experiment used it. The commands were checked by rendering the charts with `helm template`, but they have not yet been run on a cluster.

Elastic stopped maintaining this chart at 8.5.1 and recommends its ECK operator instead. GOXN does not use ECK, because ECK always enables security, and Jaeger connects here without credentials.

[OpenEBS](openebs.md) and [Prometheus](prometheus.md) must be installed first.

```bash
helm repo add elastic https://helm.elastic.co
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm upgrade --install elasticsearch elastic/elasticsearch \
    --namespace system-under-evaluation \
    --create-namespace \
    --version 8.5.1 \
    --set fullnameOverride=elasticsearch \
    --set replicas=1 \
    --set minimumMasterNodes=1 \
    --set imageTag=8.19.23 \
    --set protocol=http \
    --set createCert=false \
    --set secret.enabled=false \
    --set esJavaOpts='-Xms512m -Xmx512m' \
    --set 'esConfig.elasticsearch\.yml=xpack.security.enabled: false' \
    --set volumeClaimTemplate.storageClassName=openebs-hostpath \
    --set volumeClaimTemplate.resources.requests.storage=50Gi \
    --set 'clusterHealthCheckParams=wait_for_status=yellow&timeout=1s'

helm upgrade --install elasticsearch-exporter prometheus-community/prometheus-elasticsearch-exporter \
    --namespace system-under-evaluation \
    --version 7.4.1 \
    --set fullnameOverride=elasticsearch-exporter \
    --set es.uri=http://elasticsearch.system-under-evaluation.svc.cluster.local:9200 \
    --set serviceMonitor.enabled=true \
    --set serviceMonitor.labels.release=kube-prometheus
```

These options reproduce the manifest setup:

- `fullnameOverride=elasticsearch` keeps the service name that Jaeger's values expect.
- `replicas=1`, `minimumMasterNodes=1` and the `wait_for_status=yellow` health check allow a single node.
- `protocol=http`, `createCert=false`, `secret.enabled=false` and `xpack.security.enabled: false` turn security off.

## Deploy with manifests

This is what the `deployment` section of the persistence specs does:

```bash
kubectl create namespace system-under-evaluation
kubectl apply -f k8s/elasticsearch/
kubectl rollout status -n system-under-evaluation deployment/elasticsearch
```

Skip the first command if the namespace exists.

`k8s/elasticsearch/` contains the Elasticsearch deployment, a 50 GiB `openebs-hostpath` PVC, the service, the exporter and its `ServiceMonitor`.

## Check it

```bash
kubectl port-forward -n system-under-evaluation svc/elasticsearch 9200:9200
curl 'http://localhost:9200/_cluster/health?pretty'
```

A single node reports status `yellow` or `green`.

## Remove it

Helm route:

```bash
helm uninstall elasticsearch-exporter --namespace system-under-evaluation
helm uninstall elasticsearch --namespace system-under-evaluation
kubectl delete pvc elasticsearch-elasticsearch-0 --namespace system-under-evaluation
```

Manifest route:

```bash
kubectl delete -f k8s/elasticsearch/ --ignore-not-found
```
