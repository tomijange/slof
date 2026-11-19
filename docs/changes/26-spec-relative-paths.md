# 26. Paths relative to the spec

**Compared to GOXN:** relative paths in an experiment spec, of values files, manifests, locust files and data files, are resolved against the folder of the spec file instead of the working directory. The shipped specs in `experiments/` reach the repository with `../`, and a folder can hold a spec together with the files it uses.

## Summary

In GOXN, `oxn` opens the paths in a spec as given, so they are relative to the folder `oxn` runs in. A spec only works from the repository root, and a spec that should travel with its own values files or locust files has to name them by their path from there. This change resolves the paths while the spec is parsed, like `include` in a compiler.

| | GOXN | After this change |
|---|---|---|
| Relative paths in a spec | Against the working directory | Against the folder of the spec file |
| Shipped specs | `deployments/values/...`, `k8s/elasticsearch/`, `locust/...` | `../deployments/values/...`, `../k8s/elasticsearch/`, `../locust/...` |
| Absolute paths | As given | As given |
| Where `oxn` runs | The repository root | Any folder for experiments, the repository root for `oxn setup` |

## Resolving paths

**Now documented in:** [Experiments](../experiments.md#spec-structure), [Deployments](../deployments.md#section-format)

`load_variants` passes the folder of the spec file to `validate_syntax` as `spec_dir`, which puts it into the validation context of pydantic. Field validators on the spec model join every relative path with it and normalise the result:

| Field | Model |
|---|---|
| `values` of a Helm step | `HelmRelease` |
| `paths` of a manifests step | `Manifests` |
| `path` of a locust file | `LocustFile` |
| `data_files` | `Loadgen` |

`experiments/../locust/locust_otel_demo.py` becomes `locust/locust_otel_demo.py`, so the paths `oxn` logs and hands to `helm` and `kubectl` stay short when it runs from the repository root. Paths are resolved after the matrix is expanded, so a path in a level is resolved like one written in the spec. Without `spec_dir`, for example when a test validates a spec built in code, paths stay as written. Every command that reads a spec, `oxn`, `oxn plan`, `oxn deploy` and `oxn teardown`, goes through `load_variants`.

**Why.** A spec that names files relative to itself can be copied with them into another folder, for example to keep a suite of experiments with the values and locust files it was run with, and still runs. The same rule holds for the `yaml-language-server` comment in the first line of a spec, which already names `schema.json` relative to the spec.

**What this breaks.** Specs outside this repository with paths from the repository root must be changed to paths from their own folder. With the old paths, the deployment or the load generation fails because the files are not found.

## The shipped specs

**Now documented in:** [Experiment design](../experiment-design.md#the-specs-and-what-to-compare)

Every spec in `experiments/` and the examples in the docs and in the docstring of `DeploymentDescription` prefix their paths with `../`. The specs run the same as before.

## Tests

`oxn/tests/unit/test_experiment_specification.py` checks that relative paths of every field are resolved against the folder of the spec, that absolute paths stay, that a spec in the working directory keeps its paths, that paths stay as written without a folder, and that `load_variants` passes the folder of the spec file. `test_schema.py` also checks specs in the subfolders of `slof-experiments/`, if there are any: their first line names `schema.json` relative to the spec, they match the schema, and every file they reference exists inside their own folder. `python -m pytest oxn/tests/unit` reports 263 passing tests and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists.

## Known limitations

| Limitation | Status |
|---|---|
| `oxn setup` reads `deployments/` from the working directory and still has to run from the repository root. | Open |
| The experiment key in `store.h5` hashes the spec path as given to `oxn`, so the same spec started from another folder is stored under another key. | Open, unchanged from [change 16](16-refactorings.md#experiment-key) |
| Paths in `--extend` and `--report` stay relative to the working directory, as they come from the command line. | By design |
