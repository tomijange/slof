# 12. Removal of Docker Compose support

**Compared to GOXN:** `oxn` runs on Kubernetes only. The Docker Compose orchestrator, the treatments that only work with Docker, `--accounting` and `sue.compose` are gone, together with the `docker` and `python-on-whales` dependencies.

## Summary

GOXN still carried the Docker Compose orchestrator from the original OXN, plus treatments, resource accounting and a spec field that only worked with it. No shipped spec used any of it. The repository has no Compose file either: every spec pointed `sue.compose` at `opentelemetry-demo/docker-compose.yml`, which does not exist. This change removes that code path, about 1,500 lines with tests.

| Area | GOXN | After this change |
|---|---|---|
| Orchestrators | `docker-compose` and `kubernetes` | `kubernetes` |
| Spec | `sue.compose` required, unused on Kubernetes | No `compose` key |
| Treatments | 20 registered actions, 9 of them for Docker only | 11 actions, all for Kubernetes |
| Resource accounting | `--accounting` and `oxn/reporting/pricing.py` | Removed |
| Dependencies | `docker`, `python-on-whales` and `psutil` as direct dependencies | Removed. `psutil` still comes in through Locust |

## Orchestrator

**Now documented in:** [Architecture: one experiment run](../architecture.md#one-experiment-run)

Removed:

- `oxn/orchestration/docker_orchestration.py` and the `docker-compose` branch in `Engine.run`.
- `translate_compose_names` from the `Orchestrator` interface, and its no-op in `KubernetesOrchestrator`.

The run order no longer depends on the orchestrator: the engine deploys the SUE, then applies the compile-time treatments, then checks that the SUE is ready. On a failed deployment the engine no longer has to clean up compile-time treatments first, because none have run yet.

**Why.** Supporting two orchestrators meant two code paths in the engine. One of them could not be tested against anything in the repository, and the fork's features build on the Kubernetes deployment.

## Spec

**Now documented in:** [Experiments: spec structure](../experiments.md#spec-structure)

- `sue.compose` is gone. The line was removed from all 24 specs in `experiments/` and from the example in [Experiments](../experiments.md).
- `experiment.orchestrator` only accepts `kubernetes`. The key stays, so specs keep their format.

**What this breaks.** Specs forbid unknown keys, so a spec that still has `sue.compose` fails to load. Delete the line. A spec with `orchestrator: docker-compose` also fails.

## Treatments

**Now documented in:** [Experiments: treatments](../experiments.md#treatments)

These treatments talked to the Docker daemon on the machine running `oxn`, or edited Compose and Prometheus files on its disk and reloaded Prometheus at `localhost:9090`. On Kubernetes those containers and files do not exist.

| Action | Class | Use on Kubernetes |
|---|---|---|
| `kill` | `KillTreatment` | `kubernetes_kill` |
| `pause` | `PauseTreatment` | No replacement |
| `loss` | `PacketLossTreatment` | `kubernetes_loss` |
| `stress` | `StressTreatment` | No replacement |
| `sampling` | `PrometheusIntervalTreatment` | `kubernetes_prometheus_interval` |
| `tail` | `TailSamplingTreatment` | No replacement |
| `probl` | `ProbabilisticSamplingTreatment` | `kube_probl` |
| `otel_metrics_interval` | `MetricsExportIntervalTreatment` | `kubernetes_otel_metrics_interval` |
| `empty_docker_compose` | `EmptyDockerComposeTreatment` | `empty` or `empty_kubernetes` |
| Not registered | `ByteMonkeyTreatment` | No replacement |
| Not registered | `CorruptPacketTreatment` | `kubernetes_corrupt` |

`KubernetesNetworkDelayTreatment` and `KubernetesNetworkPacketLossTreatment` caught Docker exceptions that the Kubernetes orchestrator never raises. Those handlers are gone, and the treatments behave as before.

The empty `PacketReorderTreatment` and `SlotTreatment` placeholders stay, since they are not tied to Docker.

**What this breaks.** A treatment file passed with `--extend` that subclasses one of the removed classes, or calls `translate_compose_names`, no longer loads.

## Resource accounting

**Now documented in:** [Experiments: running an experiment](../experiments.md#running-an-experiment) for the options, [Experiment design: responses](../experiment-design.md#responses) for CPU and energy

Removed: the `--accounting` option, the `Accountant` in `oxn/reporting/pricing.py`, `Reporter.add_accountant_data` and the `accounting` section of reports.

**Why.** The accountant read CPU statistics of Docker containers through the Docker API. The engine never created one: the code that would have found the container names was commented out, so the list was always empty. With `--accounting` set, writing the report then failed on the missing accountant. On Kubernetes, CPU and energy come from the cAdvisor and Kepler responses in the specs, see [Experiment design: responses](../experiment-design.md#responses).

## Helpers and dependencies

**Now documented in:** [Getting started: install oxn](../getting-started.md#install-oxn)

- `add_env_variable` and `remove_env_variable` in `oxn/common/utils.py` edited Compose files and are gone.
- `docker` and `python-on-whales` are removed from `setup.cfg` and `requirements.txt`.
- `psutil` is removed from `setup.cfg`. It stays pinned in `requirements.txt`, because Locust depends on it.

## Tests

**Now documented in:** [Getting started: run the tests](../getting-started.md#run-the-tests)

- **Removed:** `test_orchestration.py`, `test_treatments.py` (it only covered the removed Prometheus interval, tail sampling and stress treatments), `integration/test_pricing_integration.py` and `docker_mocks.py`.
- **Trimmed:** the Docker Compose cases in `test_deployment.py` and `test_experiment_specification.py`, and the `--accounting` cases in `test_command_line.py`.
- **Mock spec:** `spec_mocks.experiment_spec_mock` uses `orchestrator: kubernetes` and an `empty` treatment instead of `pause`.

The change adds no failing tests. Right before it, `make coverage` reported 43 failing or unimportable tests, now it reports 26, and all 26 failed before. `test_cluster_proxy`, `test_deployment` and `test_experiment_specification` did not import under `make coverage` before and now pass. Still failing:

- `test_jaeger`, `test_prometheus` and `integration/test_validation`, which need a running Prometheus and Jaeger.
- Two `test_command_line` checks of an old timeout default and one `test_kubernetes_orchestration` case.
- `test_loadgen` and `test_utils`, which do not import.

## Documentation

[Architecture](../architecture.md), [Experiments](../experiments.md) and `oxn/README.md` no longer mention Docker Compose, `pricing.py` or `--accounting`.
