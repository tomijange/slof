# Locust

Locust generates load on the SUE during an experiment.

| | Managed by `oxn` | Helm (manual alternative) |
|---|---|---|
| Source | Templates in `oxn/loadgen/kubernetes/` | `deliveryhero/locust` 0.31.6 |
| Locust version | `locustio/locust:2.37.9`, the version `requirements.txt` pins | 2.15.1, the chart's default |
| Lifetime | Created and removed in each run | Until you uninstall it |
| Namespace | `oxn-loadgen`, or `loadgen.namespace` of the spec, created if missing | `system-under-evaluation` |

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
  data_files: [locust/people.json]
  target:
    name: frontend-proxy
    namespace: system-under-evaluation
    port: 8080
```

`oxn` ships every file in `locust_files` and `data_files` to the cluster in one ConfigMap, mounted into `/home/locust`, and starts master and workers with all locust files. Locust splits the users evenly between their user classes unless a class sets `weight`, and stops if two classes share a name, so the classes are `BasicInteractionUser` and `OtelDemoUser`. A locust file finds its data files next to itself, as `locust_otel_demo.py` does with `people.json`. Two shipped files cannot have the same name. `oxn` also imports every locust file locally to check it.

`oxn` also ships `oxn/loadgen/kubernetes/oxn_metrics.py`, which adds `/metrics` to the master's web UI, and a ServiceMonitor with the labels the Prometheus of target `oxn` selects by, read from its Prometheus resource. Prometheus then scrapes what the users saw every 15 s:

| Metric | Content |
|---|---|
| `locust_requests_total`, `locust_request_failures_total` | Requests and failures per request `name` and `method`, cumulative. Connection errors and status codes from 400 on are failures |
| `locust_request_duration_seconds` | Histogram per `name` and `method`, with the bucket edges of the frontend's `http_server_request_duration_seconds` |
| `locust_users` | Running users |

Query them with `job="locust-master"`. The counters start at zero in every run. After an error or ctrl-c, `oxn` removes the Locust pods, as they run outside the SUE's namespace and would otherwise outlive the run.

## Deploy with Helm

Use this to put load on the SUE by hand, for example while checking a dashboard. `oxn` does not use this chart and no reported experiment used it. The chart was checked with `helm template`, but it has not yet been run on a cluster.

The release name `manual-load` keeps these resources from clashing with the `locust-master` deployment that `oxn` creates. Remove the release before running an experiment, so that it does not add load.

```bash
kubectl create configmap slof-locustfile \
    --namespace system-under-evaluation \
    --from-file=main.py=locust/locust_basic_interaction.py

helm repo add deliveryhero https://charts.deliveryhero.io/
helm repo update

helm upgrade --install manual-load deliveryhero/locust \
    --namespace system-under-evaluation \
    --version 0.31.6 \
    --set loadtest.name=slof \
    --set loadtest.locust_locustfile_configmap=slof-locustfile \
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
kubectl delete configmap slof-locustfile --namespace system-under-evaluation
```
