# Experiments

An experiment is a YAML file that defines what to measure (responses), what to change (treatments) and how much load to apply. Specs live in `experiments/`.

## Running an experiment

```bash
mkdir -p reports
oxn experiments/test.yml --report reports/
```

| Option | Purpose |
|---|---|
| `--report DIR` | Directory for `report_<timestamp>.yaml`. It must exist. The engine needs this option even though `--help` lists it as optional. |
| `--times N` | Run the experiment N times, default 1 |
| `--randomize` | Run treatments in random order instead of spec order |
| `--extend FILE` | Load additional treatments from a Python file |
| `--accounting` | Record resource usage. Requires `--report`. |
| `--timeout T` | How long to wait for the SUE to become ready, default `1m` |
| `--keep-sue` | Skip teardown after the experiment |
| `--loglevel LEVEL` | `debug`, `info`, `warning`, `error` or `critical`, default `info` |
| `--logfile FILE` | Also write logs to a file |

## Spec structure

```yaml
experiment:
  version: 0.0.1
  orchestrator: kubernetes
  deployment:                               # optional, see Deployments
    namespaces:
      - name: system-under-evaluation
    steps:
      - helm:
          release: astronomy-shop
          chart: opentelemetry-demo
          repo: https://open-telemetry.github.io/opentelemetry-helm-charts
          version: 0.42.6
          namespace: system-under-evaluation
          values: [deployments/values/values_opentelemetry_demo.yaml]
  services:
    jaeger:
      name: jaeger
      namespace: system-under-evaluation
    prometheus: [
      { name: prometheus, namespace: system-under-evaluation, target: sue },
      { name: kube-prometheus-kube-prome-prometheus, namespace: oxn-external-monitoring, target: oxn },
    ]
  responses:
    - system_CPU:
        type: metric
        metric_name: sum(rate(container_cpu_usage_seconds_total{namespace="system-under-evaluation"}[1m]))
        left_window: 420s
        right_window: 120s
        step: 30
        target: oxn
  treatments:
    - empty_treatment:
        action: empty
        params: {
          duration: 60m,
        }
  sue:
    compose: opentelemetry-demo/docker-compose.yml
    required: [{namespace: system-under-evaluation, name: prometheus}]
  loadgen:
    run_time: 70m
    max_users: 500
    spawn_rate: 50
    locust_files: [
      { path: locust/locust_basic_interaction.py },
    ]
    target:
      name: frontend-proxy
      namespace: system-under-evaluation
      port: 8080
```

- **`deployment`** lists what `oxn` installs before the run and removes afterwards. See [Deployments](deployments.md).
- **`services`** names the Jaeger and Prometheus services. `target` picks the Prometheus a response reads from: `oxn` for the external stack, `sue` for the one inside the SUE.
- **`responses`** are the values to record. `left_window` and `right_window` set how far the observation extends before and after a treatment.
- **`treatments`** run in the listed order unless you pass `--randomize`.
- **`sue.compose`** is required by the spec model even on Kubernetes, where its value is not used.
- **`loadgen`** configures [Locust](tools/locust.md). With `target` set, `oxn` runs Locust inside the cluster.

## Treatments

These treatments are used by the shipped specs:

| Action | Effect | Parameters |
|---|---|---|
| `empty` | Changes nothing and waits, as a baseline | `duration` |
| `kube_probl` | Sets the collector's probabilistic sampling rate | `sampling_percentage`, `hash_seed` |
| `kubernetes_otel_metrics_interval` | Sets a service's OpenTelemetry metrics export interval | `namespace`, `label_selector`, `label`, `interval` |
| `kubernetes_prometheus_interval` | Sets the Prometheus scrape interval | `interval`, `evaluation_interval`, `scrape_timeout` |
| `delay` | Adds network latency to matching pods | `namespace`, `label_selector`, `label`, `delay_time`, `delay_jitter`, `duration`, `interface` |

`treatment_keys` in `oxn/core/runner.py` lists every registered action. The treatment classes in `oxn/core/treatments.py` define their parameters.

## Results

- **Report:** `reports/report_<timestamp>.yaml` holds, for each run, how every treatment and response interact, including the statistical test results, along with the load generation statistics.
- **Response data:** `store.h5` in the working directory holds the recorded data as dataframes.

Both are ignored by git.
