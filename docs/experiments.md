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
| `--times N` | Run every variant of the experiment N times, default 1. See [Running a matrix](#running-a-matrix) |
| `--randomize` | Run treatments in random order instead of spec order |
| `--only AXIS=LEVEL` | Only run the variants of the [matrix](#matrix) with this level. Repeatable |
| `--randomize-variants` | Run the variants in a new random order in every round |
| `--fail-fast` | Stop at the first failed run instead of tearing it down and starting the next one |
| `--extend FILE` | Load additional treatments from a Python file |
| `--timeout T` | How long to wait for the SUE to become ready, default `1m` |
| `--keep-sue` | Skip teardown after the experiment |
| `--dashboard` | Show the metric responses of every run live in Grafana. See [Live dashboard](#live-dashboard) |
| `--loglevel LEVEL` | `debug`, `info`, `warning`, `error` or `critical`, default `info` |
| `--logfile FILE` | Also write logs to a file |

`oxn` exits with status 1 if a run failed or was interrupted.

`oxn plan <spec>` reads and checks a spec like a run would, without touching the cluster, and lists its runs with the load time:

```text
$ oxn plan experiments/recommendation_k8_sampling.yml --times 2
experiments/recommendation_k8_sampling.yml: 8 variants x 2 runs = 16 runs, 18h40m of load plus deployment and teardown
  sampling=0.0,storage=memory          1h10m
  sampling=0.0,storage=elasticsearch   1h10m
  ...
Every round runs each variant once, in this order, 2 rounds
```

It takes `--only`, `--times` and `--extend` like a run. `--print` also prints the spec of every variant with its placeholders filled in.

### Live dashboard

With `--dashboard`, every run gets its own dashboard in the Grafana that the spec names in `services.grafana`, for `oxn setup` the [Grafana](tools/grafana.md) of kube-prometheus-stack. Without that entry, `oxn` warns and runs without a dashboard. When the load starts, `oxn` logs how to open it:

```text
Live dashboard of run 3f9a1c2e: kubectl port-forward -n oxn-external-monitoring svc/kube-prometheus-grafana 3000:80, then open http://localhost:3000/d/oxn-run-3f9a1c2e...
```

| Part | Content |
|---|---|
| Run panel | Spec, run, variant, start and the treatments with their start and end |
| One panel per metric response | Its `metric_name` and `labels`, on the Prometheus of its `target`, at its `step` |
| Treatment markers | A band per treatment from its start to its end, which grows while it runs |
| Title and tags | `<spec> · <variant> · <run>`, tagged `oxn`, the spec name and every `axis=level`, so Grafana's search filters by variant |

The dashboard starts at the longest `left_window` before the load. While the run lasts, it refreshes every 10 s and ends at now, and once the load ended, at the end of the longest `right_window`. When the responses are observed, it is pinned to that window, the one `oxn` stores, and stops refreshing. A failed or interrupted run is pinned when it is torn down. Trace responses are listed in the Run panel, not plotted.

The dashboards stay after the run. Remove them with:

```bash
kubectl delete configmap -n oxn-external-monitoring -l app.kubernetes.io/managed-by=oxn,oxn/kind=dashboard
```

The panels of a Prometheus inside the SUE, such as target `sue` in the shipped specs, are empty once the SUE is torn down, because its data goes with it. Responses of target `oxn` stay. If Grafana is missing or a ConfigMap cannot be written, `oxn` logs a warning and the run goes on.

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
          values: [../deployments/values/values_opentelemetry_demo.yaml]
  services:
    jaeger:
      name: jaeger
      namespace: system-under-evaluation
    grafana:
      name: kube-prometheus-grafana
      namespace: oxn-external-monitoring
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
      { path: ../locust/locust_basic_interaction.py },
    ]
    target:
      name: frontend-proxy
      namespace: system-under-evaluation
      port: 8080
```

- **`deployment`** lists what `oxn` installs before the run and removes afterwards. See [Deployments](deployments.md).
- Paths of values files, manifests and locust files are relative to the folder of the spec file, `../` from `experiments/` to the repository root. A folder can therefore hold a spec together with copies of the files it uses.
- **`services`** names the Jaeger and Prometheus services. `target` picks the Prometheus a response reads from: `oxn` for the external stack, `sue` for the one inside the SUE.
- **`responses`** are the values to record. `left_window` and `right_window` set how far the observation extends before and after a treatment.
- **`treatments`** run in the listed order unless you pass `--randomize`. Each one has a name, an `action` and `params`, see [Treatments](#treatments).
- **`loadgen`** configures [Locust](tools/locust.md). With `target` set, `oxn` runs Locust inside the cluster.

## Matrix

A spec can describe several experiments that differ in a few values. The optional `matrix` section, next to `experiment`, lists the values to compare as axes and their levels. `oxn` runs one variant for every combination of levels, with the `${{ ... }}` placeholders in the `experiment` section filled in. This is the matrix of `experiments/recommendation_k8_sampling.yml`, [Experiment design](experiment-design.md#the-specs-and-what-to-compare) describes the others:

```yaml
matrix:
  # a list: the values themselves are the levels
  sampling: [0.0, 5.0, 10.0, 50.0]
  # a mapping: the keys name the levels, the values can be any YAML
  storage:
    memory:
      values: ../deployments/values/values_opentelemetry_demo.yaml
      steps: []
    elasticsearch:
      values: ../deployments/values/values_opentelemetry_demo_persistence.yaml
      steps:
        - manifests:
            paths: [../k8s/elasticsearch/]
            namespace: system-under-evaluation
            wait_for: [deployment/elasticsearch]
experiment:
  deployment:
    steps:
      - ${{ storage.steps }}
      - helm:
          release: astronomy-shop
          ...
          values: ["${{ storage.values }}"]
  treatments:
    - probabilistic_head_sampling_rate:
        action: kube_probl
        params:
          sampling_percentage: ${{ sampling }}
          hash_seed: 22
```

This spec has 4 x 2 combinations, so 8 variants.

### Axes and levels

- **List.** The items are the levels: numbers, strings or booleans. `${{ sampling }}` is the item, with its type, so `sampling_percentage` gets the number `10.0`.
- **Mapping.** The keys name the levels, and the values can be anything, also lists and mappings. `${{ storage }}` is the whole value of the level, `${{ storage.values }}` one key of it.
- **Names.** Axis names are letters, digits and `_`. Level names, and the text of list levels, may only contain letters, digits and `_ . + -`, because they become part of the variant id. For other values, such as `5 %`, use a mapping.

`oxn` validates the section with pydantic. Every axis has to be used by a placeholder. Variants run in the order of the axes and their levels. Every combination runs: for a partial grid, split the spec or select variants with `--only`.

### Placeholders

- **A whole value** is replaced by the value of the level, with its type: `sampling_percentage: ${{ sampling }}`.
- **A list item** that resolves to a list is spliced into the surrounding list: `- ${{ storage.steps }}` adds no step for `memory` and one for `elasticsearch`.
- **Part of a string** is replaced by the text of the value, which then has to be a number, string or boolean: `metric_name: rate(...{pod=~"${{ service }}.*"}[90s])`.
- **Inside `{...}` or `[...]`** a placeholder needs quotes, otherwise YAML reads its braces as a mapping and the spec is invalid. The quotes do not change the type: `values: ["${{ storage.values }}"]` and `{sampling_percentage: "${{ sampling }}"}` work.
- Placeholders are not filled in keys, which is an error, comments or the `matrix` section itself.

`oxn` expands the matrix and checks every selected variant before it deploys anything. An error names the variant, for example `Can't validate variant sampling=10.0,storage=memory of experiments/x.yml`, and an unknown axis or key names the place of the placeholder.

### Running a matrix

`--times N` runs N rounds. Each round runs every variant once, in the order of the matrix, or in a new random order with `--randomize-variants`. Interleaving the variants spreads slow changes of the cluster, such as other tenants or a filling disk, over all variants, instead of adding them to the variants that run last. Every run deploys and tears down its own SUE.

`--only AXIS=LEVEL` picks variants, for example to repeat a failed one. The level is written as in the variant id, so `sampling=10.0`, not `sampling=10`. Levels of the same axis are alternatives and different axes must all match: `--only sampling=5.0 --only sampling=10.0 --only storage=memory` runs two variants.

A failed run is torn down, and the next run starts. At the end, `oxn` lists the failed runs. With `--fail-fast` it stops at the first one. If tearing down a failed run fails, `oxn` stops, so the next run does not start on a broken cluster.

`oxn deploy` and `oxn teardown` take `--only` too. They need it when the selected variants deploy different things, as `memory` and `elasticsearch` above do.

A spec without `matrix` is a single variant, and runs as before.

## Editor support

`schema.json` in the root of the repository is a JSON schema of experiment specs. With the [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) by Red Hat, VS Code uses it for completion, hover text and checks while you type. Every spec in `experiments/` names it in its first line:

```yaml
# yaml-language-server: $schema=../schema.json
```

Add the same line to a new spec, with the path relative to the spec. The schema covers:

- **Sections and fields** of the spec model, with the docstrings of the fields as hover text, and the `- name: {...}` form of responses, treatments and deployment steps.
- **Treatments.** `action` completes to the registered actions, and `params` to the params of the chosen action.
- **The matrix.** The `matrix` section, and a `${{ ... }}` placeholder in place of any value or list item.

`oxn schema` writes the file again, and `make schema` does the same. Run it after changing the spec model or a treatment, a unit test fails while the file is out of date. `oxn schema --extend FILE` adds own treatments, and `--output PATH` writes somewhere else, `-` to stdout.

`oxn` itself checks specs with the spec model, not with the schema. The schema is a little more lenient: it accepts a placeholder in every field, also where the matrix later fills in a wrong type, and checks time strings and percentages only by their form.

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
| `empty_kubernetes` | Runtime | Like `empty`, but fails with orchestrators other than Kubernetes |
| `kubernetes_loss` | Runtime | Drops a share of the packets of the pods of a deployment |
| `kubernetes_corrupt` | Runtime | Corrupts a share of the packets of the pods of a deployment |
| `kubernetes_kill` | Runtime | Kills pods of a deployment |
| `scale_deployment` | Compile-time | Scales a deployment and back to its replicas before |
| `security_context_kubernetes` | Compile-time | Adds Linux capabilities to every container of a deployment |

All of them except `empty_kubernetes` and `security_context_kubernetes` only use the [orchestrator interface](architecture.md#orchestrators), so they would also run with another orchestrator. The `kubernetes` in the other action names is historical.

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
```

A treatment changes the SUE through `self.orchestrator`, using the methods of the `Orchestrator` interface in `oxn/models/orchestrator.py`, such as `scale`, `restart` or `set_network_delay`. They take a `WorkloadSelector`, which a params model that extends `PodSelectorParams` builds as `self.params.workload`. A treatment that only uses these methods works with any orchestrator.

A treatment that needs Kubernetes objects subclasses `KubernetesTreatment` from `oxn/treatments/kubernetes.py` as well, before `RuntimeTreatment` or `CompileTimeTreatment`. `oxn` then rejects it with other orchestrators, and `self.kubernetes` is the `KubernetesOrchestrator`:

```python
from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PodSelectorParams
from oxn.treatments.kubernetes import KubernetesTreatment


class RevisionParams(PodSelectorParams):
    limit: int


class RevisionHistoryTreatment(KubernetesTreatment[RevisionParams], CompileTimeTreatment[RevisionParams]):
    action = "revision_history"
    Params = RevisionParams

    def inject(self) -> None:
        deployment = self.kubernetes.get_workload_deployment(self.params.workload)
        ...
```

## Results

- **Report:** `reports/report_<timestamp>.yaml` holds, for each run, how every treatment and response interact, including the statistical test results, along with the load generation statistics. For a variant of a matrix, the run also lists its `variant` id and its `factors`, the level of every axis, for example `{sampling: 10.0, storage: elasticsearch}`. `oxn` writes the report after every run, so an interrupted series keeps the finished runs.
- **Response data:** `store.h5` in the working directory holds the recorded data as dataframes, under `<experiment key>/<run id>/<response>`. The experiment key is the spec path as given to `oxn`, followed by the variant id in brackets for a spec with a matrix: `experiments/x.yml[sampling=10.0,storage=memory]`. Each dataframe carries the spec, variant, factors and run id in `store.get_storer(key).attrs.metadata`, so the evaluation can group runs by factor instead of by file name.
- **Experiment hash:** the first eight hex digits of the SHA-256 of the experiment key. All runs of one spec, or of one variant, share it.

Both are ignored by git.
