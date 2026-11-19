# 25. In-cluster Locust

**Compared to GOXN:** the in-cluster Locust runs in its own namespace, `oxn-loadgen`, with a pinned image, and with every locust file and data file of the spec instead of only the first locust file. Prometheus scrapes what the users saw from `/metrics` of the master. `oxn` removes the Locust pods after an error or ctrl-c, and its templates ship as package data of `oxn`.

## Summary

In GOXN, `oxn` deploys Locust into the SUE's namespace with an untagged image and only the first entry of `locust_files`. `locust_otel_demo.py` cannot run there, because it opens `locust/people.json` relative to the repository root. The load generator counts toward the SUE's CPU and energy, its view of the requests is only stored as Locust's stats after the run, and its pods outlive a failed run.

| | GOXN | After this change |
|---|---|---|
| Namespace | `system-under-evaluation` | `oxn-loadgen`, or `loadgen.namespace` of the spec, created if missing |
| Image | `locustio/locust`, untagged, pulled on every start | `locustio/locust:2.37.9`, the version `requirements.txt` pins |
| Locust files in the cluster | The first entry of `locust_files` | Every entry, plus the `data_files` they read |
| User classes | `WebsiteUser` in both locust files | `BasicInteractionUser` and `OtelDemoUser` |
| Metrics of the users' view | None | `locust_*` counters and a latency histogram, scraped by the Prometheus of target `oxn` |
| After an error or ctrl-c | Pods stay until the SUE is torn down, with `--keep-sue` for good | Pods removed |
| Templates | `locust/kubernetes/`, found through the checkout | `oxn/loadgen/kubernetes/`, package data of `oxn` |

## Own namespace

**Now documented in:** [Locust](../tools/locust.md#managed-by-oxn), [Experiment design](../experiment-design.md#what-gets-measured)

`loadgen.namespace` names the namespace of the in-cluster Locust, `oxn-loadgen` by default. `KubernetesOrchestrator.ensure_namespace` creates it before the first manifest is applied and leaves it in place afterwards. The templates take the namespace instead of naming `system-under-evaluation`, and `get_stats_from_master` reads the stats from the master in that namespace.

**Why.** Responses that sum over `system-under-evaluation`, such as `system_CPU` or `kepler_joules_namespace_combined`, included the load generator, so its CPU and energy counted as the SUE's. A change in a factor that changes the load, such as a fault that slows the responses, also changed the cost of Locust.

**What this breaks.** Namespace-wide responses of new runs leave Locust out, so they are lower than those of earlier runs and not comparable to them.

## Every locust file and data file

**Now documented in:** [Locust](../tools/locust.md#managed-by-oxn), [Experiments](../experiments.md#spec-structure)

`loadgen.data_files` lists files that the locust files read. `_shipped_files` puts every locust file, every data file and `oxn_metrics.py` into the ConfigMap `scripts-cm`, one key per file name, which the pods mount into `/home/locust`. The template writes the files as JSON, which is valid YAML, so their contents need no indentation. Master and workers start with `-f` and every locust file, in the order of the spec. Two files with the same name stop the run before anything is deployed.

`locust_otel_demo.py` opens `people.json` next to itself instead of relative to the working directory, and the shipped specs list `locust/people.json` in `data_files`. Locust stops if two user classes share a name, so the classes are now `BasicInteractionUser` and `OtelDemoUser`.

**Why.** A spec that lists two locust files ran both when Locust ran in the `oxn` process, but only the first in the cluster, without a warning. The second, `locust_otel_demo.py`, could not have run in the cluster at all, because it read its data from the repository.

**What this breaks.** The shipped specs list both locust files, so their in-cluster load now also comes from `OtelDemoUser`, which browses, adds to the cart and checks out. Locust splits the users evenly between the classes, so half of the `max_users` run each scenario. Results of new runs are not comparable to those of earlier runs, which only ran `locust_basic_interaction.py`.

## Pinned image

**Now documented in:** [Locust](../tools/locust.md)

`LOCUST_IMAGE` in `oxn/common/settings.py` names `locustio/locust:2.37.9`, the version `requirements.txt` pins for `oxn` itself, and the templates use it for master and workers. `imagePullPolicy: Always` is gone. A unit test fails when the two versions differ.

**Why.** The untagged image runs whatever Locust version was last published, so two runs of the same spec could use different versions, and the version that checks the locust files in the `oxn` process could differ from the one that runs them.

## Metrics from Locust

**Now documented in:** [Locust](../tools/locust.md#managed-by-oxn)

`oxn/loadgen/kubernetes/oxn_metrics.py` is shipped with the locust files and added to the `-f` of master and workers. It defines no users. On the master, it adds `/metrics` to the web UI, in the Prometheus text format:

| Metric | Content |
|---|---|
| `locust_requests_total`, `locust_request_failures_total` | Requests and failures per request `name` and `method`, cumulative. Connection errors and status codes from 400 on are failures |
| `locust_request_duration_seconds` | Histogram per `name` and `method`, with the bucket edges of the frontend's `http_server_request_duration_seconds` |
| `locust_users` | Running users |

`servicemonitor.yaml` adds a ServiceMonitor that selects the master's service and scrapes `/metrics` every 15 s. Its labels are those the Prometheus of target `oxn` selects ServiceMonitors by. `KubernetesOrchestrator.get_service_monitor_labels` reads them from the `serviceMonitorSelector` of the Prometheus resource behind the target's service. Without a Prometheus operator, `oxn` logs a warning and deploys no ServiceMonitor. `deploy_yaml` and `delete_yaml` handle ServiceMonitors through the `CustomObjectsApi`.

**Why.** Locust's stats are only read after the run and only as totals. The histogram shows over time what share of requests the users saw within a latency threshold, with the same bucket edges as the frontend's own histogram, so the users' view and the SUE's view can be compared in the same Prometheus. Reading the labels from the Prometheus resource keeps this working when the release of kube-prometheus-stack has another name.

## Removing the pods after an error

**Now documented in:** [Locust](../tools/locust.md#managed-by-oxn)

`start` records every manifest before it applies it, and `stop` and `kill` delete them in reverse order. `kill`, which `Engine.teardown` calls after an error or ctrl-c, logs a failed delete as a warning and goes on with the rest.

**Why.** In the SUE's namespace, the Locust pods went with the SUE. In their own namespace they would outlive a failed run and send load to the next one.

## Templates as package data

**Now documented in:** [Architecture](../architecture.md#files-read-at-runtime), [Getting started](../getting-started.md#install-oxn)

The Jinja templates moved from `locust/kubernetes/` to `oxn/loadgen/kubernetes/`, next to `locust_kubernetes.py`, and `setup.cfg` ships them as package data. `.yamllint.yml` skips them in their new place. The manifests in `locust/kubernetes/` copied from another project stay where they are. `BaseLoadGenerator` no longer calls an abstract `_read_config`, which `LocustKubernetesLoadgenerator` also called itself, so it ran twice.

**Why.** `locust_kubernetes.py` found its templates at `../../locust/kubernetes`, so a regular `pip install .` failed when load generation started.

## Tests

`oxn/tests/unit/test_experiment_specification.py` renders the manifests for `experiments/test.yml` and checks that every resource is in `oxn-loadgen`, that the ConfigMap holds both locust files, `people.json` and `oxn_metrics.py`, that master and workers run every locust file in the pinned image, that the image matches `requirements.txt`, that the ServiceMonitor selects the master's service and port with the labels of Prometheus, that `start` applies the manifests in order and `kill` removes them even if one delete fails, that there is no ServiceMonitor without a Prometheus operator, that files with the same name are rejected, and that the user classes have distinct names. It also checks the histogram of `oxn_metrics.py`. `test_orchestrator_interface.py` checks ServiceMonitors in `deploy_yaml` and `delete_yaml`, the labels from the Prometheus resource and `ensure_namespace`. `python -m pytest oxn/tests/unit` reports 258 passing tests and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists.

## Known limitations

| Limitation | Status |
|---|---|
| Locust splits the users evenly between the user classes. A spec cannot set the share of each locust file. | Open |
| `oxn` leaves the namespace `oxn-loadgen` in place after the run. | By design |
| The metrics only exist for the in-cluster Locust, not when Locust runs in the `oxn` process. | Open |
