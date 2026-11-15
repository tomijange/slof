# 19. Typed treatment params

**Compared to GOXN:** the params of every treatment are a pydantic model, and the spec checks them while it is parsed, before anything is deployed. Unknown actions and params stop the run. A `TreatmentRegistry` replaces `treatment_keys`, and treatments declare `action` and `Params` as class attributes.

## Summary

In GOXN, each treatment checked its own params in its constructor, with hand-written loops over a `params()` dict of types. The runner only built the treatments after the spec was read, and on Kubernetes after the SUE was deployed (see [change 3](03-deployment-section.md#changed-run-order-on-kubernetes)), so a typo in a treatment surfaced minutes into a run. Several of the checks also did not work. This change moves the checks into pydantic models, one per treatment, and lets the spec model validate the `params` section with the model of the `action` while it is parsed, as [Typed experiment specs](02-typed-specs.md) already does for the other sections.

| | GOXN | After this change |
|---|---|---|
| Where params are checked | `Treatment.__init__`, when the runner builds the treatments after the deploy | While the spec is parsed, before the deploy |
| How | `_validate_params()` per treatment, against `params()` | A pydantic model per treatment, named in `Treatment.Params` |
| Unknown action | Error when the runner builds the treatments | Error while the spec is parsed, listing the known actions |
| Unknown params | Ignored | Error |
| Params in the spec model | `Dict[str, Any]` | The params model of the action |
| Params in a treatment | `self.config`, a dict, with derived values like `duration_seconds` written into it | `self.params`, a frozen model, with derived values as properties |
| Action to class | `ExperimentRunner.treatment_keys`, a class-level dict extended in place | `TreatmentRegistry` in `oxn/treatments/registry.py`, one per engine |
| `action` of a treatment | Class attribute, property or method, three of them with a different value than their key | `ClassVar[str]` matching its key |
| `delay_distribution` | Accepted and ignored | Removed |

## Params models

**Now documented in:** [Experiments](../experiments.md#parameters)

`oxn/models/treatment_params.py` holds `TreatmentParams`, the base class of all params models. Unknown keys are errors and instances are frozen. It also holds what several treatments share:

| Name | Content |
|---|---|
| `DurationParams` | `duration` and the `duration_seconds` property |
| `PodSelectorParams` | `namespace`, `label_selector` and `label` |
| `NetworkParams` | Both of the above and `interface`, for the tc netem treatments |
| `TimeString` | A time string like `90s` or `1m30s` |
| `PercentString` | A percentage from `0%` to `100%` for tc |
| `PrometheusDuration` | A duration in the format of the Prometheus configuration |
| `UncheckedParams` | Params of a spec read without checking treatments |

Each treatment module defines the model of its treatment next to the class, for example `DelayParams` in `oxn/treatments/runtime/network_delay.py`. `Treatment` is generic in its params model, so `self.params.delay_time` is typed. Derived values are properties of the model: `duration_seconds` and `MetricsExportIntervalParams.interval_ms`.

`Treatment.__init__` takes `params` instead of `config`. Params from the spec are already validated and used as they are. A mapping, from tests or own code, is validated in the constructor and raises an `OxnException` if it does not match. `params()`, `_validate_params()` and `_transform_params()` are gone from the base class and all treatments.

**Why.** The spec model already rejects unknown keys and wrong types in every other section, with the location of the error. Treatment params were the last part of the spec checked by hand, and the hand-written checks had grown apart.

**What this breaks.** Code that reads `treatment.config` reads `treatment.params` and attributes instead of keys. Own treatments need `action` and `Params`, see [Own treatments](../experiments.md#own-treatments).

## Checked while the spec is parsed

**Now documented in:** [Experiments](../experiments.md#treatments), [Architecture](../architecture.md#startup)

`TreatmentDescription.params` in `oxn/models/experiment_spec.py` is typed `TreatmentParams`. Two field validators read a `TreatmentCatalog` from the pydantic validation context: one rejects an unknown `action`, the other validates `params` with the model of the action. Errors of the params model are reported together under `experiment.treatments.<n>.params`:

```text
experiment.treatments.0.params
  Value error, interface: Field required; delay_time: Expected numbers with units like 90s or 1m30s, ...; delay_distribution: Extra inputs are not permitted
experiment.treatments.1.action
  Value error, Unknown action dealy, expected one of delay, empty, ...
```

`validate_syntax` and `load_experiment_specification` in `oxn/core/validation.py` take the registry to check against, the built-in treatments by default. The engine passes its own registry, which includes the treatments from `--extend`. `oxn deploy` and `oxn teardown` pass `check_treatments=False`: they only use the `deployment` section and do not load `--extend` files, so the params of a spec with own treatments stay `UncheckedParams` there.

`SemanticValidator.validate_treatment`, which raised `NotImplementedError`, and `validate_treatments` are removed.

**Why.** The engine reads the spec before it deploys the SUE, so a wrong treatment now fails in a second instead of after the deploy. This is what the `TODO` in `oxn/models/treatment.py` asked for. Using the validation context keeps the spec model free of imports from `oxn/treatments`, which import the orchestrator.

**What this breaks.** Specs with unknown params or invalid values no longer run. All 24 specs in `experiments/` pass.

## Treatment registry

**Now documented in:** [Experiments](../experiments.md#own-treatments), [Architecture](../architecture.md#packages)

`TreatmentRegistry` in `oxn/treatments/registry.py` maps actions to treatment classes. It starts with the eleven built-in treatments, and `register()` adds own ones and replaces a built-in one with the same action. It rejects classes without a string `action` or without a `TreatmentParams` subclass as `Params`. `build()` creates the treatment a `TreatmentDescription` describes. `ExperimentRunner` takes it as `treatment_registry` instead of `additional_treatments`.

Every treatment declares `action` as a class attribute that matches its key:

| Class | `action` in GOXN | Key |
|---|---|---|
| `EmptyKubernetesTreatment` | `"empty"` (property) | `empty_kubernetes` |
| `KubernetesPrometheusIntervalTreatment` | `"sampling"` (property) | `kubernetes_prometheus_interval` |
| `KubernetesCorruptPacketTreatment`, `KubernetesMetricsExportIntervalTreatment` | A method | `kubernetes_corrupt`, `kubernetes_otel_metrics_interval` |

`EmptyKubernetesTreatment` now subclasses `EmptyTreatment` instead of copying it.

[Change 20](20-orchestrator-interface.md#treatments) renames `KubernetesPrometheusIntervalTreatment`, `KubernetesCorruptPacketTreatment` and `KubernetesMetricsExportIntervalTreatment` to `PrometheusIntervalTreatment`, `PacketCorruptionTreatment` and `MetricsExportIntervalTreatment`.

**Why.** `_extend_treatments` registered own treatments under `treatment.action`, read from the class. For a property or method that is the function object, not a string, so own treatments written like most built-in ones could not be selected. It also changed the class-level `treatment_keys` dict, so own treatments of one runner leaked into every later one.

## Fixed checks

Moving the checks into models fixed these, which the shipped specs did not hit:

| Treatment | GOXN | After this change |
|---|---|---|
| Time strings | Checked with `re.match`, so `1m30x` passed and was read as one minute | The whole string must match |
| `delay` | `namespace`, `label_selector` and `label` were required but not type-checked. The check for `delay_distribution` looked for a key `distribution`, so the value was never checked, and `inject` ignored it | Typed, `delay_distribution` removed |
| `kubernetes_kill` | Types not checked, `amount_to_kill: 0` passed | Integer of at least 1 |
| `kubernetes_otel_metrics_interval` | A missing param raised a `KeyError` instead of the message, and the format check of `interval` never ran | Required and checked |
| `scale_deployment` | A missing param raised a `KeyError` instead of the message | Required, `scale_to` an integer of at least 0 |
| `kubernetes_prometheus_interval` | The regex matched any string, also an empty one. Missing params failed an assertion in `inject` | Prometheus duration format, required |
| `kube_probl` | Missing params failed an assertion in `inject` | Required |
| `security_context_kubernetes` | `capabilities` only had to be a dict | `add` with at least one entry, optional `drop` |
| `kubernetes_loss` | `loss_percentage: 15` failed, an integer is not a float | Any number from 0 to 100 |

`validate_time_string` in `oxn/common/utils.py` matches the whole string as well.

## Tests

`oxn/tests/unit/test_treatment_params.py` covers the params of every built-in treatment, unknown actions and params, value checks, own treatments from a registry, specs read without checks and the registry's checks of `action` and `Params`. `test_runner` checks that every class's `action` matches its key. `python -m pytest oxn/tests/unit` reports 164 passing tests and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists.

## Known limitations

| Limitation | Status |
|---|---|
| Preconditions, such as whether the target deployment exists, are still checked after the deploy, since they need the running SUE. | Open |
| `oxn deploy` and `oxn teardown` do not check treatments. | By design |
| The nested errors of a params model are joined into one message per treatment, because pydantic reports an error raised inside a validator as one value error. | Open |
