# Locust

Locust generates load on the SUE during an experiment.

| | Managed by `oxn` | Helm (manual alternative) |
|---|---|---|
| Source | Templates in `locust/kubernetes/` | `deliveryhero/locust` 0.31.6 |
| Locust version | `locustio/locust`, untagged | 2.15.1, the chart's default |
| Lifetime | Created and removed in each run | Until you uninstall it |
| Namespace | `system-under-evaluation` | `system-under-evaluation` |

## Managed by oxn

You do not install Locust for an experiment. With `loadgen.target` set in the spec, `oxn` creates a ConfigMap, a `locust-master` deployment, two `locust-worker` replicas and a `locust-master` service when load generation starts. It removes them when load generation stops.

```yaml
loadgen:
  run_time: 70m
  max_users: 500
  spawn_rate: 50
  locust_files: [
    { path: locust/locust_basic_interaction.py },
    { path: locust/locust_otel_demo.py },
  ]
  target:
    name: frontend-proxy
    namespace: system-under-evaluation
    port: 8080
```

Only the first entry in `locust_files` is sent to the cluster. `oxn` also imports every listed file locally to check it, and `locust_otel_demo.py` reads `locust/people.json` from a path relative to the repository root.

## Deploy with Helm

Use this to put load on the SUE by hand, for example while checking a dashboard. `oxn` does not use this chart and no reported experiment used it. The chart was checked with `helm template`, but it has not yet been run on a cluster.

The release name `manual-load` keeps these resources from clashing with the `locust-master` deployment that `oxn` creates. Remove the release before running an experiment, so that it does not add load.

```bash
kubectl create configmap goxn-locustfile \
    --namespace system-under-evaluation \
    --from-file=main.py=locust/locust_basic_interaction.py

helm repo add deliveryhero https://charts.deliveryhero.io/
helm repo update

helm upgrade --install manual-load deliveryhero/locust \
    --namespace system-under-evaluation \
    --version 0.31.6 \
    --set loadtest.name=goxn \
    --set loadtest.locust_locustfile_configmap=goxn-locustfile \
    --set loadtest.locust_host=http://frontend-proxy:8080
```

## Check it

```bash
kubectl port-forward -n system-under-evaluation svc/manual-load-locust 8089:8089
```

Then start the test from the web interface at <http://localhost:8089>.

During an experiment, the `oxn` deployment can be checked with:

```bash
kubectl get pods -n system-under-evaluation -l role=locust-master
kubectl get pods -n system-under-evaluation -l role=locust-worker
```

## Remove it

```bash
helm uninstall manual-load --namespace system-under-evaluation
kubectl delete configmap goxn-locustfile --namespace system-under-evaluation
```
