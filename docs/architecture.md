# Architecture

`oxn` is a Python package. This page follows one `oxn <spec>` run through its modules.

## Packages

| Package | Modules |
|---|---|
| `oxn/cli/` | `main.py` (entry point), `argparser.py`, `installer.py` (`oxn setup`) |
| `oxn/core/` | `engine.py`, `runner.py`, `validation.py`, `context.py` |
| `oxn/treatments/` | `runtime/` and `compile_time/`, one module per treatment, and `registry.py`, which maps actions to treatment classes |
| `oxn/orchestration/` | `kubernetes_orchestrator.py`, `deployment.py`, `cluster_proxy.py` |
| `oxn/loadgen/` | `locust_kubernetes.py`, `file_load_generator.py` |
| `oxn/observability/` | `prometheus.py`, `jaeger.py`, `observer.py`, `responses.py` |
| `oxn/reporting/` | `report.py`, `store.py` |
| `oxn/common/` | `errors.py`, `utils.py`, `settings.py`, `log.py` |
| `oxn/models/` | `experiment_spec.py` (typed model of an experiment spec), `treatment_params.py` (base classes of treatment params) and base classes for orchestrators, load generators, treatments and responses |
| `oxn/steering/` | Sidecar container and controller that apply network treatments inside pods |

## Startup

1. `oxn/__main__.py` calls `cli/main.py`.
2. `main.py` parses the command line with `argparser.py` and sets up logging with `log.py`. `oxn setup`, `oxn deploy` and `oxn teardown` branch off here.
3. `main.py` creates an `Engine` from `engine.py`. `context.py` loads any treatments passed with `--extend`, and the engine puts them into a `TreatmentRegistry` from `treatments/registry.py`, next to the built-in ones.
4. The engine reads the spec with `validation.py`, which parses it into the `ExperimentSpec` model from `models/experiment_spec.py`. The registry checks the action and params of every treatment while the spec is parsed, so a wrong treatment stops `oxn` before anything is deployed. The orchestrators, load generator, runner and observer all read from that model.

## One experiment run

`Engine.run` repeats these steps for each run requested with `--times`:

1. **Set up.** The engine creates a `KubernetesOrchestrator` from `kubernetes_orchestrator.py` and an `ExperimentRunner` from `runner.py`, which builds the treatments of the spec with the registry.
2. **Deploy.** If the spec has a `deployment` section, `deployment.py` installs the stack.
3. **Compile-time treatments.** The runner applies the treatments from `treatments/compile_time/`, which change the SUE's configuration before the load starts. They patch the deployed SUE and restart its pods. The orchestrator then checks that the SUE is ready.
4. **Load.** The engine creates a `LocustKubernetesLoadgenerator` from `locust_kubernetes.py`, which starts Locust in the cluster.
5. **Runtime treatments.** The runner applies each treatment from `treatments/runtime/` and then cleans it up.
6. **Observe.** `observer.py` collects the response variables from `responses.py`, which query `prometheus.py` and `jaeger.py`.
7. **Store and report.** `store.py` writes each response to `store.h5`, and `report.py` gathers the data for the report.
8. **Tear down.** `deployment.py` removes the stack, unless `--keep-sue` is set.

After the last run, the report is written to the `--report` directory.

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

`Engine.teardown` cleans up based on the phase. It kills the load generator in the `load` phase and tears down the SUE in every phase from `orchestration` to `teardown`, unless `--keep-sue` is set. It ends every run. When a run fails or is interrupted with ctrl-c, `main.py` logs the phase it stopped in and calls it too.

## Older modules

| Module | Purpose |
|---|---|
| `loadgen/file_load_generator.py` | Older load generator, not used to run experiments |

## Files read at runtime

`oxn` reads these repository files while running, so they must stay in place:

- `locust/kubernetes/{configmap,master,worker,service}.yaml`: Jinja templates for the Locust pods
- `locust/locust_*.py` and `locust/people.json`: Locust scenarios and their data
- `deployments/values/` and `k8s/elasticsearch/`: deployment inputs
