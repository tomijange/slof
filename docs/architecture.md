# Architecture

`oxn` is a Python package. This page follows one `oxn <spec>` run through its modules.

## Packages

| Package | Modules |
|---|---|
| `oxn/cli/` | `main.py` (entry point), `argparser.py`, `installer.py` (`oxn setup`), `plan.py` (`oxn plan`) |
| `oxn/core/` | `engine.py`, `runner.py`, `validation.py`, `matrix.py`, `schema.py` (`oxn schema`), `context.py` |
| `oxn/treatments/` | `runtime/` and `compile_time/`, one module per treatment, `registry.py`, which maps actions to treatment classes, and `kubernetes.py`, the base class of Kubernetes-only treatments |
| `oxn/orchestration/` | `kubernetes_orchestrator.py`, `kubernetes_objects.py`, `deployment.py`, `cluster_proxy.py` |
| `oxn/loadgen/` | `locust_kubernetes.py`, `file_load_generator.py` |
| `oxn/observability/` | `prometheus.py`, `jaeger.py`, `observer.py`, `responses.py`, `dashboard.py` for `--dashboard` |
| `oxn/reporting/` | `report.py`, `store.py` |
| `oxn/common/` | `errors.py`, `utils.py`, `settings.py`, `log.py` |
| `oxn/models/` | `experiment_spec.py` (typed model of an experiment spec), `treatment_params.py` (base classes of treatment params), `orchestrator.py` (the orchestrator interface), `workload.py` (the workloads it acts on) and base classes for load generators, treatments and responses |
| `oxn/steering/` | Sidecar container and controller that apply network faults inside pods, Kubernetes only |

## Startup

1. `oxn/__main__.py` calls `cli/main.py`.
2. `main.py` parses the command line with `argparser.py` and sets up logging with `log.py`. `oxn setup`, `oxn plan`, `oxn deploy`, `oxn teardown` and `oxn schema` branch off here.
3. `main.py` creates an `Engine` from `engine.py`. `context.py` loads any treatments passed with `--extend`, and the engine puts them into a `TreatmentRegistry` from `treatments/registry.py`, next to the built-in ones.
4. The engine reads the spec with `validation.py`. `matrix.py` expands its `matrix` section into one raw spec per variant, with the placeholders filled in, and applies `--only`. `validation.py` parses every variant into the `ExperimentSpec` model from `models/experiment_spec.py`. The registry checks the action and params of every treatment while the spec is parsed, so a wrong treatment stops `oxn` before anything is deployed. The orchestrators, load generator, runner and observer all read from that model.

## One experiment run

`Engine.schedule` orders the runs: `--times` rounds, each of which runs every variant once. `Engine.run` repeats these steps for each run. If a step raises an `OxnException`, the engine logs it, tears the run down and starts the next one, unless `--fail-fast` is set. At the end it raises an `OxnException` that lists the failed runs.

1. **Set up.** The engine creates a `KubernetesOrchestrator` from `kubernetes_orchestrator.py` and an `ExperimentRunner` from `runner.py` for the spec of the variant. The runner builds the treatments with the registry and knows the experiment key of the variant.
2. **Deploy.** If the spec has a `deployment` section, `deployment.py` installs the stack.
3. **Compile-time treatments.** The runner applies the treatments from `treatments/compile_time/`, which change the SUE's configuration before the load starts. They patch the deployed SUE and restart its pods. The orchestrator then checks that the SUE is ready.
4. **Load.** The engine creates a `LocustKubernetesLoadgenerator` from `locust_kubernetes.py`, which starts Locust in the cluster. With `--dashboard`, `RunDashboard` from `observability/dashboard.py` then publishes the live dashboard of the run.
5. **Runtime treatments.** The runner applies each treatment from `treatments/runtime/` and then cleans it up. With `--dashboard`, it updates the dashboard after each treatment starts and ends.
6. **Observe.** `observer.py` collects the response variables from `responses.py`, which query `prometheus.py` and `jaeger.py`. With `--dashboard`, the dashboard is then pinned to the observed window.
7. **Store and report.** `store.py` writes each response to `store.h5`, under the experiment key of the variant and with its factors as metadata, and `report.py` gathers the data for the report.
8. **Tear down.** `deployment.py` removes the stack, unless `--keep-sue` is set.

After every run, the report is written to the `--report` directory.

## Orchestrators

The engine, load generators, observability clients and treatments use the SUE through the `Orchestrator` interface in `models/orchestrator.py`. Besides deploying the SUE and finding addresses, it covers everything the treatments do:

| Group | Methods |
|---|---|
| Lifecycle | `orchestrate`, `ready`, `teardown` |
| Addresses | `get_address_for_service`, `get_prometheus_url` and `get_jaeger_url`, external through the API server proxy or `internal=True` for the cluster DNS name, `http_session` for external urls |
| Workloads | `get_instances`, `kill_instance`, `get_replicas`, `scale`, `restart`, `is_ready`, `get_environment_variable`, `set_environment_variable` |
| Network faults | `prepare_network_faults`, `set_network_delay`, `set_network_loss`, `set_network_corruption`, `remove_network_faults` |
| Telemetry configuration | Get and set the global scrape values of the SUE's Prometheus and the collector's probabilistic sampler. Setting restarts the component |

Workloads are addressed with a `WorkloadSelector` from `models/workload.py`: a namespace and a label with its value, as in the `namespace`, `label_selector` and `label` params of a treatment. A `WorkloadInstance` is one running copy.

`KubernetesOrchestrator` is the only implementation. A workload is a deployment and an instance is a pod. The scrape values and the sampler are written to the `prometheus` and `otel-collector` ConfigMaps in `system-under-evaluation`. Network faults go through the steering sidecar: `prepare_network_faults` adds the container from `steering/steering_container.py` to the deployment with `SteeringController`, which then sends the pods `tc netem` commands through the API server proxy. Its methods that take `V1Deployment` and `V1Pod` objects, such as `get_deployment` and `apply_security_context_to_deployment`, are for Kubernetes-only code, and `deploy_yaml` and `delete_yaml` create and delete the Locust manifests.

Treatments built on `KubernetesTreatment` from `treatments/kubernetes.py` reject other orchestrators when the runner builds them. Of the built-in ones, these are `empty_kubernetes` and `security_context_kubernetes`. `LocustKubernetesLoadgenerator` needs a `KubernetesOrchestrator` too, and `Prometheus` and `Jaeger` use its API server proxy when they get one.

## Phases and cleanup

`Engine.phase` holds the step of the current run, as a value of the `Phase` enum in `engine.py`. Changes are logged at debug level.

| Phase | Steps above | SUE may be deployed | Load generator may be running |
|---|---|---|---|
| `initialization` | 1, in the first run | No | No |
| `orchestration` | 2 | Yes | No |
| `preparation` | 3, and creating the load generator | Yes | No |
| `load` | 4 to 6 | Yes | Yes |
| `reporting` | 7 | Yes | No |
| `teardown` | 8, skipped with `--keep-sue` | Yes | No |
| `completed` | After each run, and 1 of the next run | No | No |

`Engine.teardown` cleans up based on the phase. It kills the load generator in the `load` phase and tears down the SUE in every phase from `orchestration` to `teardown`, unless `--keep-sue` is set. It ends every run, and `Engine.run` calls it after a failed run before the next one starts. When a run is interrupted with ctrl-c, fails with `--fail-fast` or cannot be torn down, `main.py` logs the phase it stopped in and calls it too.

## Older modules

| Module | Purpose |
|---|---|
| `loadgen/file_load_generator.py` | Older load generator, not used to run experiments |

## Files read at runtime

`oxn` reads these repository files while running, so they must stay in place:

- `locust/kubernetes/{configmap,master,worker,service}.yaml`: Jinja templates for the Locust pods
- `locust/locust_*.py` and `locust/people.json`: Locust scenarios and their data
- `deployments/values/` and `k8s/elasticsearch/`: deployment inputs
