# 22. Experiment specs as matrices

**Compared to GOXN:** the 23 `recommendation_k8_*` specs are five specs with a [matrix](21-experiment-matrix.md), with 31 variants. The variants of a spec differ only in their levels, so the comparisons inside a spec are exact. Six variants change in small ways against their old files, eight are new.

## Summary

In GOXN, every combination of settings was its own file, and the files had drifted apart: some set the scrape interval and their comparison partners did not, and the reference of the export interval specs set one service where the others set 18. [Experiment design](../experiment-design.md#where-the-comparisons-are-not-exact) listed six such differences. This change groups the specs by what they compare and writes each group as one spec whose variants share everything but their levels.

| | GOXN | After this change |
|---|---|---|
| Files | 23 `recommendation_k8_*.yml` | 5 `recommendation_k8_*.yml` with a matrix |
| Runs for one round | 23 | 31 |
| Lines of YAML | 8348 | 1883 |
| Comparisons that differ in more than the factor | 6 | 0 inside a spec |
| Reference for the fault | A spec of another group, `base_1s_otel_minimal` for `delay_1s_otel` | `fault=none` of the same telemetry level |

## The specs

**Now documented in:** [Experiment design](../experiment-design.md#the-specs-and-what-to-compare)

| Spec | Axes | Variants | Replaces |
|---|---|---|---|
| `recommendation_k8_sampling.yml` | `sampling` x `storage` | 8 | `base_{0,5,10,50}_percent`, `base_{5,10,50}_percent_persistence` |
| `recommendation_k8_metric_export.yml` | `export_interval` x `storage` | 6 | `base_{1s,30s,1m}_otel`, `base_{1s,30s}_otel_persistence` |
| `recommendation_k8_scrape_mesh.yml` | `scrape` x `mesh` | 6 | `base_1m_otel_persistence`, its `_scrape_5s`, `_scrape_30s` and `_istio` variants |
| `recommendation_k8_fault.yml` | `fault` x `telemetry` | 8 | `delay_{5_percent,10_percent,1m_otel,1s_otel}` |
| `recommendation_k8_minimal.yml` | `telemetry` | 3 | `base_{10_percent,50_percent,1s_otel}_minimal` |

The response queries, services, SUE section and load are copied unchanged from the old specs. Levels with structure carry it themselves: `storage=elasticsearch` adds the Elasticsearch step and its values file, `mesh=istio` the Istio namespaces and releases, and the `telemetry` levels the treatments they need. A level of `fault` is one whole treatment entry, the empty treatment or the delay.

**Why.** One file per group keeps the shared part in one place, so variants cannot drift apart again, and the comparisons the thesis makes are the variants of one spec.

## Changes against the old specs

**Now documented in:** [Experiment design](../experiment-design.md#specs-before-the-matrix)

Every old spec was compared with the variant that replaces it, after expanding the matrix. 15 are identical. Two list a compile-time and a runtime treatment in the other order, which the runner does not depend on, because it runs all compile-time treatments before the runtime ones. Six differ:

| Old spec | Variant now | Difference | Why |
|---|---|---|---|
| `base_5_percent`, `base_10_percent`, `base_50_percent` | `sampling=…,storage=memory` | Also set the scrape interval to 60 s with rule evaluation every 30 s | `base_0_percent`, their reference, set it, so the comparison differed in the rule evaluation interval |
| `base_30s_otel`, `base_30s_otel_persistence` | `export_interval=30s` | Also set the scrape interval | The 1 s and 60 s specs set it |
| `base_1m_otel` | `export_interval=60s,storage=memory` | Sets all 18 services to 60 s instead of only recommendation | The 1 s and 30 s variants restart 18 pods before the load, the 60 s one restarted one |
| `base_1m_otel_persistence_istio` | `scrape=60s,mesh=istio` | Also records `sampling_rates` | The variants of a spec record the same responses. A response without data is skipped with a warning |

These variants are new:

| Variant | What it adds |
|---|---|
| `recommendation_k8_sampling.yml[sampling=0.0,storage=elasticsearch]` | The reference for the Elasticsearch sampling variants |
| `recommendation_k8_metric_export.yml[export_interval=60s,storage=elasticsearch]` | The reference for the Elasticsearch export variants, which used `base_1m_otel_persistence` from the scrape group |
| `recommendation_k8_scrape_mesh.yml[scrape={5s,30s},mesh=istio]` | The scrape intervals inside the mesh |
| `recommendation_k8_fault.yml[fault=none,telemetry=…]`, four variants | References for the delay with the same telemetry, recorded with the trace responses |

Runs of only the old combinations select them with `--only`, for example `--only mesh=none` and `--only scrape=60s`.

**What this breaks.** Data of the old specs in `store.h5` stays under the old file names, new runs are stored under the spec and variant. The notebooks in `evaluation/` select data by the old names, so they need the new keys or the factors in the metadata of each dataframe. [Specs before the matrix](../experiment-design.md#specs-before-the-matrix) maps every old name to its variant. Results of the six changed variants are not directly comparable with results of their old specs.

## Tests

`ShippedExperimentsTest` loads every variant of every spec in `experiments/` with `load_variants`, checks its deployment and that the five recommendation specs have 8, 6, 3, 8 and 6 variants. `python -m pytest oxn/tests/unit` reports 213 passing tests and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists.

## Known limitations

| Limitation | Status |
|---|---|
| The notebooks in `evaluation/` still read the old store keys. | Open |
| The metric export spec still has one treatment for each of the 18 services, see [change 21](21-experiment-matrix.md#known-limitations). | Open |
| The fault and minimal specs do not set the scrape interval, as their old specs did not. | By design |
| Variants of different specs are not designed to be compared, see [Where the comparisons are not exact](../experiment-design.md#where-the-comparisons-are-not-exact). | By design |
