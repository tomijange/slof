# 21. Experiment matrix

**Compared to GOXN:** one spec can describe several experiments. An optional `matrix` section lists the values to compare, and `oxn` runs one variant per combination, with `${{ ... }}` placeholders filled in. `--times` runs rounds that interleave the variants. A failed run is torn down and the next one starts. Results are keyed by variant and carry its factors. `oxn plan` lists the runs of a spec without touching the cluster.

## Summary

In GOXN, a spec is one experiment. To compare values, such as four trace sampling rates with and without Elasticsearch, every combination is its own file. `experiments/` holds 23 `recommendation_k8_*` specs of 81 to 503 lines that repeat each other except for a few values. Copies drift apart: the 0 % sampling spec sets the scrape interval, the 5, 10 and 50 % specs do not. The evaluation then selects the data by file name. This change adds a `matrix` section, so the shared part is written once and the values that change are listed as axes.

| | GOXN | After this change |
|---|---|---|
| Comparing values | One spec file per combination | One spec with a `matrix` section, one variant per combination |
| `--times N` | Runs one spec N times in a row | Runs N rounds, each of which runs every variant once |
| Order of the variants | The order you start the specs in | Matrix order, or random per round with `--randomize-variants` |
| Running a subset | Pick the files | `--only AXIS=LEVEL` |
| A failed run | Stops all later runs | Is torn down, the next run starts. `--fail-fast` stops |
| Exit status after a failed run | 0 | 1 |
| Store key | `<spec path>/<run>/<response>` | `<spec path>[<variant id>]/<run>/<response>`, with factors as metadata |
| Report | Written after the last run, every run lists the interactions of all earlier runs too | Written after every run, every run lists its own interactions and its variant |
| Listing the runs | None | `oxn plan` |

## The matrix section

**Now documented in:** [Experiments](../experiments.md#matrix)

`oxn/core/matrix.py` reads the raw YAML before the spec model does. `Matrix` is a pydantic `RootModel` of the `matrix` section: each key is an axis, and its levels are the keys of a mapping or the items of a list, which a `BeforeValidator` turns into a mapping that names each level by its value. `Matrix.variants()` builds every combination with `itertools.product`. `Variant` is one combination, with an `id` like `sampling=10.0,storage=memory` and the `factors`, the level of every axis. `expand()` returns the selected variants, each with its raw spec without the `matrix` section and with the placeholders filled in, and the spec model parses it like any other spec.

Placeholders are `${{ axis }}` or `${{ axis.key }}`:

| Where | Result |
|---|---|
| A whole value | The value of the level, with its type |
| A list item that resolves to a list | The list is spliced in |
| Part of a string | The text of the value, which has to be a number, string or boolean |
| A key | Not filled in, an error |
| A comment, the matrix section | Not filled in |

Pydantic rejects an empty matrix or axis, a list level that is not a number, string or boolean, and axis and level names with other characters than letters, digits and `_` (axes) or `_ . + -` (levels). Expanding stops with the location for an unknown axis, a key a level does not have, a placeholder in a key, a malformed placeholder and an axis no placeholder uses. Every combination runs, there is no `exclude` or `include`.

**Why.** A matrix keeps the shared part of a series of experiments in one place, so variants cannot drift apart the way the copied files did. Placeholders are explicit and work for structural differences too, such as an extra deployment step, which a patch of the spec could not express without rules for merging lists. Pydantic validates the section like the rest of the spec, so only filling in the placeholders is own code. A partial grid is split into several specs or run with `--only`, which keeps the section to axes and levels. The syntax is the one of GitHub Actions. It passes yamllint and PyYAML in block style, and needs quotes inside `{...}` and `[...]`.

**What this breaks.** Nothing. A spec without `matrix` is one variant without levels. [Change 22](22-matrix-specs.md) converts the shipped specs.

## Loading and validating variants

**Now documented in:** [Experiments](../experiments.md#placeholders), [Architecture](../architecture.md#startup)

`load_variants` in `oxn/core/validation.py` expands the matrix, applies `--only` and validates every selected variant. It returns `ExperimentVariant`s, which hold the variant, its `ExperimentSpec` and its raw spec. An invalid variant stops `oxn` before anything is deployed, with an error that names it, for example `Can't validate variant duration=long,users=100 of experiments/x.yml`. `load_experiment_specification` still returns one `ExperimentSpec` and raises for a matrix with more than one variant.

**Why.** A typo in one variant should not surface hours into a series.

## Running the variants

**Now documented in:** [Experiments](../experiments.md#running-a-matrix), [Architecture](../architecture.md#one-experiment-run)

`Engine.schedule` orders the runs: `--times` rounds, each of which runs every variant once, in a new random order per round with `--randomize-variants`. `Engine.run` runs them with `_run_once`, which is the body of the old loop with the spec of the variant. The runner gets the variant and has an `experiment_key`. `--only` selects variants, and `--fail-fast` restores the old behaviour of stopping at the first failure.

After a failed run, the engine logs the error, tears the run down and starts the next one. At the end, it raises an `OxnException` that lists the failed runs, and `main.py` exits with status 1, as it now does after any failure or ctrl-c. If tearing down a failed run fails, the exception goes to `main.py`, which retries the teardown and stops.

**Why.** Runs of the same spec right after each other give slow changes of the shared cluster, such as other tenants, a filling disk or temperature, to whichever variant runs at the time, and make them look like an effect of the variant. Interleaving spreads them over all variants. A series of 14 runs of 70 minutes runs unattended, so one failed deploy should not cost the rest of the night.

**What this breaks.** `--times N` with a single spec behaves as before, except that a failed run no longer stops the remaining ones. Scripts that relied on exit status 0 after a failed run see 1.

## oxn plan

**Now documented in:** [Experiments](../experiments.md#running-an-experiment)

`oxn plan <spec>` in `oxn/cli/plan.py` loads the spec like a run, with `--only`, `--times` and `--extend`, and prints the variants with their load time and the total. `--print` prints the spec of every variant with the placeholders filled in, as YAML documents. It does not touch the cluster.

**Why.** To check a matrix and its placeholders, and to know how long a series takes before starting it.

## Results

**Now documented in:** [Experiments](../experiments.md#results)

| | GOXN | After this change |
|---|---|---|
| Experiment key in `store.h5` | The spec path | The spec path, followed by `[<variant id>]` for a variant of a matrix |
| Metadata of a stored dataframe | None | `spec`, `variant`, `factors` and `run` in `store.get_storer(key).attrs.metadata` |
| Experiment hash | SHA-256 of the spec path ([change 16](16-refactorings.md#experiment-key)) | SHA-256 of the experiment key |
| Report entry of a run | `interactions`, `loadgen` | Also `variant` and `factors` for a variant of a matrix |

`write_dataframe` in `oxn/reporting/store.py` takes the metadata. `Reporter.begin_run` starts the entry of a run and forgets the interactions of the previous one, and the engine writes the report after every run.

**Why.** The factors of a run belong to its data, so the notebooks in `evaluation/` can group by `sampling` and `storage` instead of parsing file names. In GOXN, `Reporter.interactions` grew over all runs and each run listed the interactions of the earlier ones. That was already wrong with `--times`, and a matrix makes series longer. Writing the report after every run keeps the finished runs if a later one is interrupted.

**What this breaks.** For specs without a matrix, keys and hashes stay the same. Data of a spec that is converted to a matrix is stored under new keys, so the notebooks need the new keys or the metadata.

## Deploy and teardown

**Now documented in:** [Deployments](../deployments.md#deploy-and-tear-down-by-hand)

`oxn deploy` and `oxn teardown` take `--only`. If the selected variants have different `deployment` sections, they stop and list the variants.

**Why.** Tearing down the `memory` variant of a spec does not remove the Elasticsearch of its `elasticsearch` variant.

## Tests

`oxn/tests/unit/test_matrix.py` covers the combinations, typed values, splicing and strings, the pydantic checks of the matrix, every placeholder error, selections, validating variants from a file, the schedule, continuing after a failed run, `--fail-fast`, store keys and metadata, the hash and report of a variant, the new options, `oxn deploy` with several deployments and `oxn plan`. The engine tests in `test_deployment.py` set `engine.variants` and check that a failed deploy is torn down by the engine, or left to `main.py` with `--fail-fast`. `python -m pytest oxn/tests/unit` reports 212 passing tests and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists.

## Known limitations

| Limitation | Status |
|---|---|
| The shipped `recommendation_k8_*` specs are separate files, not matrices. | Done in [change 22](22-matrix-specs.md) |
| The 1 s and 30 s export specs copy one treatment for each of 18 services. A matrix does not help there, the treatment would need to accept several services. | Open |
| Warnings logged while treatment params are checked, such as the one for a high sampling rate, appear once per variant. | Open |
| `oxn plan` only adds up the load time, not deployment and teardown. | Open |
| Separate specs, and specs with different matrices, still run one after the other. | By design |
| There is no `exclude` or `include`, a partial grid needs several specs or `--only`. | By design |
| Placeholders are not filled in keys, so treatment and response names are the same in every variant. | By design |
