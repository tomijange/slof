# Architecture

`oxn` is a Python package. This page follows one `oxn <spec>` run through its modules.

## Packages

| Package | Modules |
|---|---|
| `oxn/cli/` | `main.py` (entry point), `argparser.py`, `installer.py` (`oxn setup`) |
| `oxn/core/` | `engine.py`, `runner.py`, `treatments.py`, `validation.py`, `context.py` |
| `oxn/orchestration/` | `kubernetes_orchestrator.py`, `deployment.py`, `cluster_proxy.py`, `docker_orchestration.py` |
| `oxn/loadgen/` | `locust_kubernetes.py`, `config_load_generator.py`, `file_load_generator.py`, `loadgen_config.py` |
| `oxn/observability/` | `prometheus.py`, `jaeger.py`, `observer.py`, `responses.py` |
| `oxn/reporting/` | `report.py`, `store.py`, `pricing.py` |
| `oxn/common/` | `errors.py`, `utils.py`, `settings.py`, `log.py` |
| `oxn/models/` | `experiment_spec.py` (typed model of an experiment spec) and base classes for orchestrators, load generators, treatments and responses |
| `oxn/steering/` | Sidecar container and controller that apply network treatments inside pods |

## Startup

1. `oxn/__main__.py` calls `cli/main.py`.
2. `main.py` parses the command line with `argparser.py` and sets up logging with `log.py`. `oxn setup`, `oxn deploy` and `oxn teardown` branch off here.
3. `main.py` creates an `Engine` from `engine.py`. The engine reads the spec with `validation.py`, which parses it into the `ExperimentSpec` model from `models/experiment_spec.py`. The orchestrators, load generator, runner and observer all read from that model.
4. `context.py` loads any treatments passed with `--extend`.

## One experiment run

`Engine.run` repeats these steps for each run requested with `--times`:

1. **Set up.** The engine creates a `KubernetesOrchestrator` from `kubernetes_orchestrator.py` and an `ExperimentRunner` from `runner.py`.
2. **Deploy.** If the spec has a `deployment` section, `deployment.py` installs the stack.
3. **Compile-time treatments.** The runner applies treatments that change the SUE's configuration before the load starts. On Kubernetes they patch the deployed SUE and restart its pods. With Docker Compose they run before step 2, because they change what gets built. The orchestrator then checks that the SUE is ready.
4. **Load.** The engine creates a `LocustKubernetesLoadgenerator` from `locust_kubernetes.py`, which starts Locust in the cluster.
5. **Runtime treatments.** The runner applies each treatment from `treatments.py` and then cleans it up.
6. **Observe.** `observer.py` collects the response variables from `responses.py`, which query `prometheus.py` and `jaeger.py`.
7. **Store and report.** `store.py` writes each response to `store.h5`, and `report.py` gathers the data for the report.
8. **Tear down.** `deployment.py` removes the stack, unless `--keep-sue` is set.

After the last run, the report is written to the `--report` directory.

## Older modules

| Module | Purpose |
|---|---|
| `orchestration/docker_orchestration.py` | Older Docker Compose orchestrator, selected with `orchestrator: docker-compose` |
| `loadgen/config_load_generator.py`, `loadgen/file_load_generator.py` | Older load generators, imported by the engine but not used to run experiments |

## Files read at runtime

`oxn` reads these repository files while running, so they must stay in place:

- `locust/kubernetes/{configmap,master,worker,service}.yaml`: Jinja templates for the Locust pods
- `locust/locust_*.py` and `locust/people.json`: Locust scenarios and their data
- `deployments/values/` and `k8s/elasticsearch/`: deployment inputs
