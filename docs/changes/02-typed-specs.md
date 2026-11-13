# 2. Typed experiment specs

**Compared to GOXN:** experiment specs are loaded into one pydantic model instead of being checked with `schema` and passed around as nested dicts, and unknown keys stop the run.

## Summary

GOXN validated a spec with `schema`, then every module read it again with lookups such as `config["experiment"]["loadgen"].get("max_users", 100)`, each with its own defaults and `assert`s. This change describes the whole spec as a pydantic model. The engine and every module it hands the spec to read typed attributes instead. Spec files keep their format.

| | GOXN | After this change |
|---|---|---|
| Validation | `schema` (`core/validation.py`: `syntactic_schema`) | pydantic, `oxn/models/experiment_spec.py` |
| What modules receive | Nested dicts | `ExperimentSpec` |
| Defaults | Repeated in each module | Once, in the model |
| Unknown keys | Ignored | Rejected at load time |
| Dependency | `schema` | `pydantic>=2.0` |

## The spec model

**Now documented in:** [Experiments: spec structure](../experiments.md#spec-structure)

`oxn/models/experiment_spec.py` defines `ExperimentSpec`, `Experiment`, `Services`, the metric and trace response descriptions, the treatment description, `Sue` and `Loadgen`. `core/validation.py` reads the YAML and returns an `ExperimentSpec`. `Engine.load_experiment_specification()` replaces `read_experiment_specification()` and `validate_syntax()`.

These modules now receive the model instead of a dict: the engine, both orchestrators, the runner, the observer, the response variables and the load generators.

**Why.**

- **One place for structure and defaults.** The model holds each default once, such as `max_users=100`, `spawn_rate=10` and `limit=100`. The code reads plain attributes.
- **Typos fail loudly.** Every section forbids unknown keys (`extra="forbid"`), so a misspelled key stops the run at load time instead of being silently ignored.
- **Existing specs keep their format.** Responses and treatments are still written as `- name: {...}`. A validator flattens each entry into a model with a `name` field. Responses are a discriminated union on `type` (`metric` or `trace`), so an error message names the fields of the right type.
- **Room to grow.** New sections, such as the `deployment` section from [the next change](03-deployment-section.md), are typed like the rest.

`orchestrator` is limited to `docker-compose` or `kubernetes` by the model. That is why the engine no longer has its own "Unknown orchestrator" branch. Since [Removal of Docker Compose support](12-remove-docker-compose.md), only `kubernetes` is accepted.

## What this breaks

- **Specs with extra keys.** A spec that GOXN accepted because it ignored a key now fails to load. Remove or fix the key.
- **Code that indexes the spec.** Code that reads `config["experiment"][...]` must use attributes, such as `config.experiment.responses`. Treatments are not affected, they still receive their `params` as a dict.

## Tests

`test_experiment_specification.py` covers the model. `test_validation.py` and the spec mocks in `spec_mocks.py` were updated for it.

## Known limitations

Nothing is left open by this change.
