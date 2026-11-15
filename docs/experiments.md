# Experiments

An experiment is a YAML file that defines what to measure (responses), what to change (treatments) and how much load to apply. Specs live in `experiments/`. [Experiment design](experiment-design.md) explains what the shipped specs measure and which ones to compare.

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
- **`treatments`** run in the listed order unless you pass `--randomize`. Each one has a name, an `action` and `params`, see [Treatments](#treatments).
- **`loadgen`** configures [Locust](tools/locust.md). With `target` set, `oxn` runs Locust inside the cluster.

## Treatments

A treatment is either compile-time or runtime. Compile-time treatments change the SUE's configuration after it is deployed and before the load starts, which restarts the affected pods. They stay in place until the runtime treatments end. Runtime treatments run one after another while the load runs.

Each entry of `treatments` names the treatment, picks it with `action` and configures it with `params`:

```yaml
treatments:
  - delay_treatment:
      action: delay
      params:
        namespace: system-under-evaluation
        label_selector: app.kubernetes.io/name
        label: recommendation
        interface: eth0
        duration: 60m
        delay_time: 45ms
        delay_jitter: 45ms
```

`oxn` checks the `action` and every parameter when it reads the spec, before it deploys anything. An unknown action, a missing or unknown parameter and a value of the wrong type or format stop the run with an error that names the treatment and the parameter, for example `experiment.treatments.0.params: interface: Field required`. `oxn deploy` and `oxn teardown` only read the `deployment` section and skip this check.

### Built-in treatments

The first five are used by the shipped specs.

| Action | Kind | Effect |
|---|---|---|
| `empty` | Runtime | Changes nothing and waits, as a baseline |
| `kube_probl` | Compile-time | Sets the collector's probabilistic sampling rate and restarts the collector |
| `kubernetes_otel_metrics_interval` | Compile-time | Sets `OTEL_METRIC_EXPORT_INTERVAL` of a deployment |
| `kubernetes_prometheus_interval` | Compile-time | Sets the global scrape interval, evaluation interval and scrape timeout of the SUE's Prometheus |
| `delay` | Runtime | Adds network latency to the pods of a deployment |
| `empty_kubernetes` | Runtime | Like `empty`, but only with the Kubernetes orchestrator |
| `kubernetes_loss` | Runtime | Drops a share of the packets of the pods of a deployment |
| `kubernetes_corrupt` | Runtime | Corrupts a share of the packets of the pods of a deployment |
| `kubernetes_kill` | Runtime | Kills pods of a deployment |
| `scale_deployment` | Compile-time | Scales a deployment and back to its replicas before |
| `security_context_kubernetes` | Compile-time | Adds Linux capabilities to every container of a deployment |

### Parameters

Parameters without a default are required.

| Parameter | Used by | Format | Default |
|---|---|---|---|
| `duration` | `empty`, `empty_kubernetes`, `delay`, `kubernetes_loss`, `kubernetes_corrupt` | Time string: numbers with the units `us`, `ms`, `s`, `m`, `h` or `d`, like `90s` or `1m30s` | |
| `namespace`, `label_selector`, `label` | All treatments that target a deployment | The deployment whose `label_selector` label has the value `label`, like `app.kubernetes.io/name` and `recommendation` | |
| `interface` | `delay`, `kubernetes_loss`, `kubernetes_corrupt` | Network interface inside the pods, usually `eth0` | |
| `delay_time` | `delay` | Time string | |
| `delay_jitter` | `delay` | Time string | `0ms` |
| `delay_correlation` | `delay` | Percentage, like `25%` | `0%` |
| `loss_percentage` | `kubernetes_loss` | Number from 0 to 100 | |
| `corrupt_percentage` | `kubernetes_corrupt` | Percentage, like `10%` | |
| `corrupt_correlation` | `kubernetes_corrupt` | Percentage | `0%` |
| `amount_to_kill` | `kubernetes_kill` | Integer, at least 1 | |
| `scale_to` | `scale_deployment` | Integer, at least 0 | |
| `sampling_percentage` | `kube_probl` | Number from 0 to 100. Above 20, `oxn` warns | |
| `hash_seed` | `kube_probl` | Integer | |
| `interval` | `kubernetes_otel_metrics_interval` | Time string | |
| `interval`, `evaluation_interval`, `scrape_timeout` | `kubernetes_prometheus_interval` | Prometheus duration, like `15s` or `1m30s` | |
| `capabilities` | `security_context_kubernetes` | `{add: [NET_ADMIN], drop: [...]}`, `add` with at least one entry | `drop: []` |

Each treatment module in `oxn/treatments/runtime/` and `oxn/treatments/compile_time/` defines its parameters as a pydantic model next to the treatment class. The shared parts, such as the time string and the deployment selector, are in `oxn/models/treatment_params.py`.

### Own treatments

`--extend FILE` loads the treatment classes from a Python file. A treatment subclasses `RuntimeTreatment` or `CompileTimeTreatment` from `oxn/models/treatment.py`, sets `action` to the key it is selected with and `Params` to its params model. `oxn` checks its params like those of the built-in treatments, and an own treatment with the action of a built-in one replaces it.

```python
import time

from oxn.models.treatment import RuntimeTreatment
from oxn.models.treatment_params import DurationParams


class PauseParams(DurationParams):
    reason: str = "baseline"


class PauseTreatment(RuntimeTreatment[PauseParams]):
    action = "pause"
    Params = PauseParams

    def inject(self) -> None:
        time.sleep(self.params.duration_seconds)

    def clean(self) -> None:
        pass

    def preconditions(self) -> bool:
        return True

    def _validate_orchestrator(self) -> bool:
        return True
```

## Results

- **Report:** `reports/report_<timestamp>.yaml` holds, for each run, how every treatment and response interact, including the statistical test results, along with the load generation statistics. Its `experiment_key` is the first eight hex digits of the SHA-256 of the spec path as given to `oxn`, so all runs of one spec share it.
- **Response data:** `store.h5` in the working directory holds the recorded data as dataframes.

Both are ignored by git.
