# 16. Refactorings

**Compared to GOXN:** the engine tracks the step of a run in one `phase` field instead of the `sue_running` and `loadgen_running` flags, and cleans up from one `Engine.teardown` method. Treatments live in one module each, split into runtime and compile-time packages. The report's `experiment_key` identifies the spec, and timestamps carry type annotations. Exceptions are logged by one `log_exception` helper.

## Summary

This change reworks parts of the engine and runner from GOXN without new features. Most of it concerns cleanup after an error or ctrl-c. GOXN marked a run with two flags that covered only part of it, so a deployment that failed or was interrupted left the SUE half installed. A `Phase` enum in `oxn/core/engine.py` replaces both flags. The change also splits the 1200-line `treatments.py` into one module per treatment, separated by kind. It fixes the experiment hash, which ignored the spec, and adds type annotations to timestamps. One helper in `oxn/common/log.py` now logs caught exceptions in the same format everywhere.

| | GOXN | After this change |
|---|---|---|
| Run state | `sue_running` and `loadgen_running` | `Engine.phase`, one of seven `Phase` values |
| Cleanup code | Flag checks in `main()`, separate from the teardown at the end of a run | `Engine.teardown()`, used by both |
| `keep_sue` | Argument of `Engine.run` | Argument of `Engine(...)` |
| Failed deployment | Not torn down. [Change 3](03-deployment-section.md#changed-run-order-on-kubernetes) made the engine tear it down itself | Torn down by `Engine.teardown()` |
| Ctrl-c during deployment or readiness check | SUE left as it is | Torn down by `Engine.teardown()` |
| Load generator fails or is interrupted while starting | Not killed | Killed |
| Log after an error or ctrl-c | Error or "Trying to shut down gracefully" | Also names the phase, for example `Interrupted in phase load` |
| Treatment code | All in `oxn/core/treatments.py` | `oxn/treatments/runtime/` and `oxn/treatments/compile_time/`, one module per treatment |
| Runtime or compile-time | Each class overrides `is_runtime()` | Each class subclasses `RuntimeTreatment` or `CompileTimeTreatment` |
| `experiment_key` in the report | `e3b0c442` for every spec | Differs per spec path, for example `7a2840cc` for `experiments/test.yml` |
| Timestamps on runners and treatments | No annotations | `float \| None` |
| Logging a caught exception | `log_exception` in `main.py`, the same code written out in `observer.py`, only the message in `packet_loss.py` | `log_exception` in `oxn/common/log.py`, used by all three |

## Engine phases

**Now documented in:** [Architecture: phases and cleanup](../architecture.md#phases-and-cleanup)

`Engine.run` moves through these phases in each run:

| Phase | Starts | SUE may be deployed | Load generator may be running |
|---|---|---|---|
| `initialization` | When the engine is created | No | No |
| `orchestration` | Before `orchestrate()` deploys the SUE | Yes | No |
| `preparation` | After deployment: compile-time treatments, readiness and precondition checks | Yes | No |
| `load` | Before the load generator starts: runtime treatments, observation | Yes | Yes |
| `reporting` | After the load generator stops: storing and reporting the responses | Yes | No |
| `teardown` | Before the SUE is removed, skipped with `--keep-sue` | Yes | No |
| `completed` | At the end of each run | No | No |

`Phase.sue_deployed` and `Phase.loadgen_running` answer the two questions in the last columns. Phase changes are logged at debug level.

Three phases start earlier than the old flags did:

- **`orchestration`** starts before deployment, while `sue_running` was only set after it. The engine's own teardown of a failed deployment from [change 3](03-deployment-section.md#changed-run-order-on-kubernetes) is gone, because `Engine.teardown()` now covers that case, and a ctrl-c during deployment too.
- **`load`** starts before `start()`, while `loadgen_running` was only set after it.
- **`teardown`** keeps `sue_deployed` true while the SUE is removed. If the teardown fails or is interrupted, the next call tries again, as `main()` did with `sue_running`.

**Why.** Two flags could only describe two states, and cleanup was missing wherever they lagged behind the run. One phase per step makes the state explicit, and the log shows where a long run on the cluster stopped.

**What this breaks.** Code that read `engine.sue_running` or `engine.loadgen_running` reads `engine.phase.sue_deployed` or `engine.phase.loadgen_running` instead.

## One teardown method

**Now documented in:** [Architecture: phases and cleanup](../architecture.md#phases-and-cleanup)

`Engine.teardown()` cleans up based on the phase. It kills the load generator if `loadgen_running` is true. It tears down the SUE if `sue_deployed` is true and `Engine.keep_sue` is not set, and enters `teardown` while it does. Then it enters `completed`.

The engine calls it at the end of every run. `main()` calls it in its `finally` block, in place of the flag checks it had in GOXN, and logs the phase the run stopped in before. `keep_sue` moved from `Engine.run` to the `Engine` constructor, so `teardown()` takes no arguments. `main()` passes `--keep-sue` there.

**Why.** GOXN tore down the SUE in two places with two conditions: at the end of a run in `Engine.run`, and after an error in `main()`. One method makes both paths clean up the same way.

**What this breaks.** Pass `keep_sue` to `Engine(...)` instead of to `run()`. A failed deployment is now torn down after the error is logged, not before.

## Treatment modules

**Now documented in:** [Architecture: packages](../architecture.md#packages), [Experiments: treatments](../experiments.md#treatments)

The treatment classes moved from `oxn/core/treatments.py` to the new `oxn/treatments/` package, one module per treatment:

| Kind | Module | Classes | Actions |
|---|---|---|---|
| Runtime | `runtime/empty.py` | `EmptyTreatment`, `EmptyKubernetesTreatment` | `empty`, `empty_kubernetes` |
| Runtime | `runtime/network_delay.py` | `KubernetesNetworkDelayTreatment` | `delay` |
| Runtime | `runtime/packet_loss.py` | `KubernetesNetworkPacketLossTreatment` | `kubernetes_loss` |
| Runtime | `runtime/packet_corruption.py` | `KubernetesCorruptPacketTreatment` | `kubernetes_corrupt` |
| Runtime | `runtime/kill.py` | `KubernetesKillTreatment` | `kubernetes_kill` |
| Runtime | `runtime/planned.py` | `PacketReorderTreatment`, `SlotTreatment` | None, both are unimplemented stubs |
| Compile-time | `compile_time/security_context.py` | `KubernetesApplySecurityContextTreatment` | `security_context_kubernetes` |
| Compile-time | `compile_time/metrics_export_interval.py` | `KubernetesMetricsExportIntervalTreatment` | `kubernetes_otel_metrics_interval` |
| Compile-time | `compile_time/head_sampling.py` | `KubernetesProbabilisticHeadSamplingTreatment` | `kube_probl` |
| Compile-time | `compile_time/deployment_scale.py` | `DeploymentScaleTreatment` | `scale_deployment` |
| Compile-time | `compile_time/prometheus_interval.py` | `KubernetesPrometheusIntervalTreatment` | `kubernetes_prometheus_interval` |

`oxn/models/treatment.py` adds two base classes next to `Treatment`. `RuntimeTreatment.is_runtime()` returns `True` and `CompileTimeTreatment.is_runtime()` returns `False`, so the classes no longer override it. Every treatment keeps the kind it had. The runner still splits the treatments by `is_runtime()`, so treatments loaded with `--extend` can subclass `Treatment` directly as before. The class bodies are unchanged apart from the base class, the removed `is_runtime()` and imports trimmed to what each module uses.

**Why.** One file of 1200 lines held eleven treatments of two kinds, and the kind was a `return True` or `return False` at the end of each class. In a module and package of its own, each treatment is easier to find, and the package shows its kind, which decides when it runs.

**What this breaks.** Imports from `oxn.core.treatments` fail. Import from `oxn.treatments.runtime` or `oxn.treatments.compile_time` instead.

## Experiment key

**Now documented in:** [Experiments: results](../experiments.md#results)

`ExperimentRunner._compute_hash` is meant to hash the spec path. In GOXN it overwrote the encoded path with an empty `hashlib.sha256()` before using it, so every spec got the hash of nothing. The report's `experiment_key`, the first eight hex digits of that hash, was `e3b0c442` for every experiment. The hash now includes the path. Without a spec path, `hash` is `None` and so is `short_hash`. In GOXN, `hash` was never set in that case, and `short_hash` raised `AttributeError`.

**Why.** The key is meant to tell experiments apart in reports.

**What this breaks.** Reports from before this change all have `experiment_key: e3b0c442`, so the key cannot match them to newer reports. The key hashes the path as given on the command line, so `experiments/test.yml` and `./experiments/test.yml` get different keys.

## Type annotations

`ExperimentRunner.experiment_start` and `experiment_end`, and `Treatment.start` and `end`, are annotated as `float | None`. They start as `None` and hold UTC unix timestamps once set. `ExperimentRunner.hash` and `short_hash` are annotated as `str | None`.

**Why.** Without annotations, type checkers infer `None` from the initial value and flag every later use of the timestamps.

## Logging exceptions

`oxn/common/log.py` now has `log_exception(logger, exception, message=None, level=logging.ERROR)`. It logs `ClassName: message` on the given logger, after `message` if one is passed, and adds the stack trace when that logger is on debug level. `main.py` defined it for its own logger, and `observer.py` wrote out the same code for a failed capture. Both call the shared helper now. The packet loss treatment uses it too when its cleanup fails, so that error now names the exception class and has a stack trace at debug level.

The observer's warning changes from `Failed to capture latency, proceeding. <message>` to `Failed to capture latency, proceeding: ValueError: <message>`, and stays a warning.

**Why.** Every module that catches an exception and goes on should log it the same way, with the stack trace one `--loglevel debug` away.

## Tests

`test_deployment.py` checks that a run passes through every phase in order, that `--keep-sue` skips `teardown`, and that a failed deployment stops in `orchestration` without cleaning up. It checks what `Engine.teardown()` cleans up in each phase and with `--keep-sue`, and that a failed teardown stays in `teardown`. It also checks that `main()` passes `--keep-sue` to the engine and calls `Engine.teardown()` after an error or ctrl-c.

`test_runner.py` checks that every registered action keeps its kind, that the runtime and compile-time packages only hold treatments of their kind, that the experiment hash differs per spec path and that a runner without a spec path has no `short_hash`.

`test_log.py` checks that `log_exception` logs the class name and message as an error, puts the message given in front and uses the given level, and adds the stack trace only on debug level.

## Known limitations

| Limitation | Status |
|---|---|
| When Locust runs in the cluster, killing the load generator stops nothing there. Its pods stay until the SUE teardown removes their namespace, or keep running with `--keep-sue`. | Open, unchanged from GOXN |
| `Engine.teardown()` only tears down the SUE and does not clean up treatments, see the `TODO` in `engine.py`. Treatments on the SUE go away with it, but with `--keep-sue`, or for treatments outside the SUE's namespaces, they stay applied after an error or ctrl-c. | Open, unchanged from GOXN |
