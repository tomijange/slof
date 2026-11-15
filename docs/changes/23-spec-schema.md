# 23. JSON schema of experiment specs

**Compared to GOXN:** `schema.json` in the root of the repository describes experiment specs for editors, and every spec names it in its first line. VS Code completes sections, fields, treatment actions and their params, shows field docs and marks mistakes while you type. `oxn schema` generates the file from the spec model and the treatments.

## Summary

In GOXN, the format of a spec was only defined by the code that read it, so mistakes surfaced when `oxn` ran. [Typed experiment specs](02-typed-specs.md) and [typed treatment params](19-treatment-params.md) made it a pydantic model, and this change exports that model as a JSON schema in the form of the YAML files.

| | GOXN | After this change |
|---|---|---|
| Format of a spec | Defined by the code | The spec model, exported as `schema.json` |
| Editor | No completion or checks | Completion, hover text and checks with the Red Hat YAML extension |
| Treatment params in the editor | None | The params of the chosen action |
| Keeping it current | | `oxn schema` or `make schema`, a unit test fails when the file is out of date |

## The schema

**Now documented in:** [Experiments](../experiments.md#editor-support)

`oxn/core/schema.py` builds the schema with pydantic's `models_json_schema` from `ExperimentSpec` and the params model of every action in the `TreatmentRegistry`, and changes it to the form of the files:

| The pydantic schema | The schema of the files |
|---|---|
| Responses and treatments as objects with a `name` field | Entries like `- system_CPU: {...}`, a mapping with one key |
| Deployment steps with a `kind` field | `- helm: {...}` and `- manifests: {...}` |
| `params` of any treatment | An `if`/`then` branch per action that selects its params model, with the first paragraph of the treatment's docstring |
| No matrix | The `matrix` section, and a `${{ ... }}` placeholder accepted in place of every value, list item and mapping value |

`SpecModel` and `TreatmentParams` set `use_attribute_docstrings`, so the docstrings below fields become their descriptions. `TimeString`, `PercentString` and `PrometheusDuration` add a pattern and examples to the schema only, their validators are unchanged. The patterns of the matrix and its placeholders come from `oxn/core/matrix.py`, so the schema and the expansion agree.

**Why.** Specs are long and hand-written, and a typo in a treatment param or a response used to show up only when `oxn` read the spec. The editor now marks it at once. Generating the schema from the models keeps it in step with what `oxn` accepts.

## oxn schema

**Now documented in:** [Experiments](../experiments.md#editor-support)

`oxn schema` writes the schema to `schema.json`, `--output` elsewhere or to stdout with `-`, and `--extend` adds own treatments. `make schema` runs it. Every spec in `experiments/` starts with `# yaml-language-server: $schema=../schema.json`, which the YAML extension reads, so the repository needs no editor settings.

## Tests

`oxn/tests/unit/test_schema.py` checks that `schema.json` matches the generated schema and that every spec names it, that own treatments get their params, and, with `jsonschema` from `requirements-dev.txt`, that every shipped spec is valid and that ten typical mistakes are found at their place. `python -m pytest oxn/tests/unit` reports 219 passing tests and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists.

## Known limitations

| Limitation | Status |
|---|---|
| The schema accepts a placeholder in every field, also where the matrix fills in a value of the wrong type. `oxn` finds that when it reads the spec. | By design |
| Fields without a docstring, such as most params of `delay`, have no hover text. | Open |
| The Lint workflow does not run the tests, so only the local test run notices an outdated `schema.json`. | Open |
