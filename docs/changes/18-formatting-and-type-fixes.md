# 18. Formatting and type fixes

**Compared to GOXN:** The repository passes `make lint`: the Python code is formatted with Ruff and passes Ruff's checks and ty, and the YAML passes yamllint. The orchestrator and treatment base classes match their implementations, `kubernetes_corrupt` no longer crashes, and the unused `config_load_generator.py` and `loadgen_config.py` are gone.

## Summary

This change applies the tools from [Linting, formatting and type checking](17-lint-and-format.md) to the code. Most of it is formatting and type hints. Where ty found code that fails at runtime, the change fixes that code.

| Area | GOXN | After this change |
|---|---|---|
| Formatting | Mixed styles, unsorted imports | Ruff's formatter in all 57 files it changed, imports sorted |
| Ruff findings | 85, among them 35 unused imports and 5 unused variables | None |
| ty findings | 160 | None |
| yamllint findings | 43 | None, with braces allowed to hold one space and three copied manifests skipped |
| Base classes | `Orchestrator` and `Treatment` declare other signatures than their subclasses use | Same signatures in base class and subclasses |
| `kubernetes_corrupt` | Fails on inject with an `AttributeError` | Corrupts packets for the given duration |
| Load generators | Four modules, two of them unusable | `locust_kubernetes.py` and `file_load_generator.py` |
| Unit tests | `test_loadgen` and `test_utils` do not import, 16 others fail | 150 pass, 3 fail |
| Commit hook | None | `make hooks` installs a pre-commit hook that runs `make lint` |

## Formatting

**Now documented in:** [Getting started](../getting-started.md#lint-and-format)

`make format` reformatted 57 Python files and sorted the imports in 41 of them. The unused imports and variables, f-strings without placeholders and a redefined import that `ruff check` found are removed.

**Why.** The formatting is one change of its own, so later diffs only show what they change.

## YAML

**Now documented in:** [Getting started](../getting-started.md#lint-and-format)

The specs, Helm values and the Locust `service.yaml` template get a space after `#` in full-line comments, two spaces before inline comments, a final newline and no trailing spaces. The `params` of `delay_treatment` in `experiments/test.yml` and the `accessLogging` list in `values_istiod.yaml` are indented like the rest of their file. Every changed file parses to the same data as before.

`.yamllint.yml` allows one space inside braces, as in `{ name: prometheus, target: sue }`, and skips `master-deployment.yaml`, `slave-deployment.yaml` and `scripts-cm.yaml` in `locust/kubernetes/`.

**Why.** The specs write flow mappings with spaces inside the braces throughout, which is a style, not an error. The three manifests are copies from the kubernetes-locust project that the README in the same folder describes. `oxn` does not use them, so they stay as they were.

## Commit hook

**Now documented in:** [Getting started](../getting-started.md#commit-hook)

`.githooks/pre-commit` runs `make lint` before every commit. `make hooks` installs it by setting `core.hooksPath` to `.githooks`, and the hook puts `.venv/bin` on the path.

**Why.** Now that the repository passes `make lint`, the hook keeps it that way before the Lint workflow runs. A plain hook needs no further package and uses the tools pinned in `requirements-dev.txt`, while the pre-commit framework would install and pin its own copies.

**What this breaks.** Nothing until `make hooks` runs. Then a commit with lint findings stops, unless it uses `--no-verify`.

## Base classes

**Now documented in:** [Architecture](../architecture.md#packages)

The abstract `Orchestrator` in `oxn/models/orchestrator.py` now declares the signatures that `KubernetesOrchestrator` implements and its callers use: `ready(expected_services=None, timeout=120)`, `get_address_for_service(namespace, name)` and `get_prometheus_address(target)`. `running_services` is removed from both. It was declared as a property returning names but implemented as a method returning `V1Service` objects, and nothing called it.

`Treatment._validate_orchestrator()` takes no arguments, as in every treatment and in the call in `Treatment.__init__`. The check that the treatments called through `super()` is now `Treatment._orchestrator_is_one_of(valid_for)`. `Treatment.preconditions()` returns `True` after logging, so treatments that only call `super()` keep working.

[Change 20](20-orchestrator-interface.md#treatments) removes `_orchestrator_is_one_of`: `_validate_orchestrator()` returns `True` by default, and Kubernetes-only treatments subclass `KubernetesTreatment`. It also moves `patch_deployment_to_include_steering_sidecar_container` to `SteeringController.add_sidecar`.

`ResponseVariable` declares `name`, `start` and `end` as set by its subclasses and `data` as an optional dataframe. `Observer.variables()` returns metric and trace variables, which `Reporter.gather_interaction` expects. `SemanticValidator` takes the orchestrator that `Prometheus` and `Jaeger` need, so it can be created again.

**Why.** ty checks calls against the declared types. With the old declarations, every caller of the orchestrator and every treatment was an error, and a new orchestrator or treatment written against the base class would not have worked.

## Runtime fixes

ty found code that fails when it runs:

| Where | Before | After |
|---|---|---|
| `KubernetesCorruptPacketTreatment` (`kubernetes_corrupt`) | Called `orchestrator.orchestrate.set_network_corruption`, an `AttributeError` on inject and clean. It also waited for the duration twice and logged "packet loss" | Calls the orchestrator, waits once and logs "packet corruption" |
| `packet_loss` and `kubernetes_corrupt` preconditions | A failing `get_deployment` raised a `NameError` in the error message | The message names the label selector |
| `patch_deployment_to_include_steering_sidecar_container` | An empty response raised an `AttributeError`, because a `V1Deployment` has no `status_code` | Raises an `OrchestratorException` |
| `get_address_for_service` | Error messages printed `cProfile.label`, imported by mistake. A service and pod without an IP returned `None` | Messages name the service. No IP raises an `OrchestratorResourceNotFoundException` |
| `is_deployment_ready` | A deployment without `replicas` in its status raised a `TypeError` | It is not ready |
| `kube_probl` (`head_sampling.py`) | Any error while reading the ConfigMap raised an `AttributeError` on `e.body` | Catches the `ApiException` it expects |
| `deployment_scale.py` | A deployment without `spec.replicas` failed an assertion when scaled back | Scales back to 1, the Kubernetes default |
| Treatment files from `--extend` | Loaded with `SourceFileLoader.load_module()`, which Python 3.15 removes | Loaded with `exec_module()` and registered in `sys.modules` as before |

`humanize_utc_timestamp` no longer uses the deprecated `datetime.utcfromtimestamp` and returns the same values. The six network methods of `KubernetesOrchestrator` share one `_pods_of_deployment` helper.

**Why.** These paths only run on errors or with specific treatments, so the experiments in `experiments/` did not reach them. A type error there is a crash during an experiment.

**What this breaks.** Code that calls `SemanticValidator(experiment_spec)` now passes an orchestrator as well.

## Load generators

**Now documented in:** [Architecture](../architecture.md#older-modules)

`oxn/loadgen/config_load_generator.py`, `oxn/loadgen/loadgen_config.py` and `oxn/tests/unit/test_loadgen.py` are removed.

**Why.** Nothing used them. `loadgen_config.py` was a copy of `config_load_generator.py` that did not import. Both read the spec as a dict, which [Typed experiment specs](02-typed-specs.md) replaced, and called `get_address_for_service` with arguments it does not take. `test_loadgen.py` imported a module that does not exist.

## Tests

`test_jaeger` and `test_prometheus` pass a mock orchestrator and pass again. `test_utils` imports again: its test of `defer_cleanup`, which [Removal of Docker Compose support](12-remove-docker-compose.md) removed, is gone. The other tests narrow optional and union types before they use them, and `integration/test_validation` creates a `KubernetesOrchestrator` for the `SemanticValidator`.

`python -m pytest oxn/tests/unit` reports 150 passing and 3 failing tests. Before this change, two test modules did not import, and without them 16 tests failed. All 3 still failing tests failed before.

## Known limitations

| Limitation | Status |
|---|---|
| `test_command_line` expects the timeout as a string, but the parser converts it to seconds. `test_kubernetes_orchestration` reads services from the current cluster and fails where `grafana` is not running in `monitoring`. | Open |
| Many functions still have no type hints, so ty checks their bodies with inferred types only. | Open |
| `file_load_generator.py` is not used to run experiments either. | Open |
