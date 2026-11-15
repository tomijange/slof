# Changes

SLOF builds on [GOXN](https://github.com/JulianLegler/goxn) by Julian Legler. This section lists every change since then, one page per change, and compares each one to GOXN. Read them in order: later pages build on earlier ones.

```{toctree}
:hidden:

01-package-layout
02-typed-specs
03-deployment-section
04-api-server-proxy
05-oxn-setup
06-skip-missing-responses
07-logging
08-stack-versions
09-repository-layout
10-documentation-site
11-current-stack-specs
12-remove-docker-compose
13-rename-to-slof
14-remove-setup-scripts
15-material-theme
16-refactorings
17-lint-and-format
18-formatting-and-type-fixes
```

## In order

| # | Change | Compared to GOXN |
|---|---|---|
| 1 | [Package layout](01-package-layout.md) | Modules in packages by responsibility, absolute imports, entry point `oxn.cli.main:main` |
| 2 | [Typed experiment specs](02-typed-specs.md) | A pydantic spec model instead of `schema` and nested dicts. Unknown keys stop the run |
| 3 | [A deployment section in the spec](03-deployment-section.md) | Specs deploy and remove their own stack, `oxn deploy`, `oxn teardown`, `--keep-sue`. Compile-time treatments run after the deploy on Kubernetes |
| 4 | [Reaching the cluster through the API server proxy](04-api-server-proxy.md) | `oxn` runs anywhere `kubectl` works. Failed `tc` commands are logged |
| 5 | [`oxn setup`](05-oxn-setup.md) | One command installs OpenEBS, Prometheus and Kepler in order, instead of `setup/*.sh` |
| 6 | [Missing response data no longer aborts the run](06-skip-missing-responses.md) | A response without data is skipped with a warning |
| 7 | [Logging](07-logging.md) | Module loggers, a coloured console format, timings for every phase |
| 8 | [Stack versions](08-stack-versions.md) | Current charts and images, and `test.yml` uses their metric names |
| 9 | [Repository layout](09-repository-layout.md) | Values and dashboard in `deployments/`, obsolete scripts removed, new Makefile targets |
| 10 | [Documentation site](10-documentation-site.md) | A Sphinx site with guides and tool pages instead of one README |
| 11 | [Specs for the current stack](11-current-stack-specs.md) | Every spec has a `deployment` section and uses the metric names of the current charts. New Experiment design page |
| 12 | [Removal of Docker Compose support](12-remove-docker-compose.md) | Kubernetes only. The Compose orchestrator, Docker-only treatments, `--accounting` and `sue.compose` are gone |
| 13 | [Rename to SLOF](13-rename-to-slof.md) | The project is called SLOF, with its own repository and docs site. The package and `oxn` command keep their names |
| 14 | [Removal of the setup scripts](14-remove-setup-scripts.md) | No `setup/` folder. `oxn setup` prepares the cluster, Getting started covers installing |
| 15 | [Material theme for the docs](15-material-theme.md) | The docs site uses `sphinx-immaterial`, with tabs, search, light and dark mode and the theme's Mermaid renderer |
| 16 | [Refactorings](16-refactorings.md) | One `phase` field and `Engine.teardown()` instead of `sue_running` and `loadgen_running`. Failed or interrupted deployments are torn down. One module per treatment in `oxn/treatments/runtime` and `compile_time`. `experiment_key` differs per spec. One `log_exception` helper in `oxn/common/log.py` |
| 17 | [Linting, formatting and type checking](17-lint-and-format.md) | Ruff for Python, yamllint for YAML, ty for type hints, `make lint`, `make format` and a Lint workflow. No `.vscode/` folder |
| 18 | [Formatting and type fixes](18-formatting-and-type-fixes.md) | `make lint` passes: code formatted with Ruff and free of Ruff, ty and yamllint findings. Base classes match their subclasses, `kubernetes_corrupt` works, two unused load generators removed. `make hooks` installs a pre-commit hook for `make lint` |

## GOXN and now

What differs from GOXN today, by area. "Changed in" points to the change pages, "Documented in" to the pages that describe the current state.

| Area | GOXN | Now | Changed in | Documented in |
|---|---|---|---|---|
| Name and repository | GOXN, `JulianLegler/goxn` | SLOF, `tomijange/slof` | [13](13-rename-to-slof.md#name-and-links) | [Overview](../index.md) |
| Code layout | About 25 modules side by side in `oxn/` | Packages by responsibility, one module per treatment | [1](01-package-layout.md#packages), [16](16-refactorings.md#treatment-modules) | [Architecture](../architecture.md#packages) |
| Spec format | `schema` validation, unknown keys ignored, `sue.compose` required | Typed pydantic model, unknown keys rejected, no `compose` | [2](02-typed-specs.md#the-spec-model), [12](12-remove-docker-compose.md#spec) | [Experiments](../experiments.md#spec-structure) |
| Orchestrators | `kubernetes`, with no-op deploy and teardown, and `docker-compose` | `kubernetes`, which deploys and tears down the spec's stack | [3](03-deployment-section.md#what-deploy-and-teardown-do), [12](12-remove-docker-compose.md#orchestrator) | [Deployments](../deployments.md), [Architecture](../architecture.md#one-experiment-run) |
| SUE lifecycle | `run_experiment_suite.sh` runs `helm` by hand | A `deployment` section in every spec, `oxn deploy` and `oxn teardown` | [3](03-deployment-section.md#what-deploy-and-teardown-do), [11](11-current-stack-specs.md#deployment-sections) | [Deployments](../deployments.md#shipped-setups) |
| Run order on Kubernetes | Compile-time treatments, then deploy | Deploy, then compile-time treatments | [3](03-deployment-section.md#changed-run-order-on-kubernetes) | [Architecture](../architecture.md#one-experiment-run) |
| Cluster access | Direct HTTP to pod and cluster IPs, `oxn` inside the cluster network | Kubernetes API server proxy | [4](04-api-server-proxy.md#the-cluster-proxy) | [Deployments](../deployments.md#reaching-the-cluster-network) |
| Cluster setup | `setup/*.sh` and README commands | `oxn setup`, no `setup/` folder | [5](05-oxn-setup.md#the-command), [14](14-remove-setup-scripts.md#setup-scripts) | [Getting started](../getting-started.md#prepare-the-cluster) |
| Treatments | Kubernetes and Docker-only treatments, `is_runtime()` per class | Kubernetes treatments only, in a runtime and a compile-time package | [12](12-remove-docker-compose.md#treatments), [16](16-refactorings.md#treatment-modules) | [Experiments](../experiments.md#treatments) |
| Cleanup after an error or ctrl-c | Two flags, a failed or interrupted deployment is left behind | `Engine.phase`, every phase from deployment to teardown is cleaned up | [16](16-refactorings.md#engine-phases) | [Architecture](../architecture.md#phases-and-cleanup) |
| Experiment key in reports | `e3b0c442` for every spec | Hash of the spec path | [16](16-refactorings.md#experiment-key) | [Experiments](../experiments.md#results) |
| Missing data | A response without data aborts the run | It is skipped with a warning | [6](06-skip-missing-responses.md#skipping-responses-without-data) | [Experiments](../experiments.md#results) |
| Resource accounting | `--accounting` with Docker container statistics | Removed, CPU and energy come from responses | [12](12-remove-docker-compose.md#resource-accounting) | [Experiment design](../experiment-design.md#responses) |
| Logging | One uncoloured format, some modules on the root logger | Module loggers, coloured console, timings | [7](07-logging.md#console-format) | [Experiments](../experiments.md#running-an-experiment) |
| Chart versions | kube-prometheus-stack 62.5.1, OpenTelemetry Demo 0.36.4, old Kepler chart | 92.16.1, 0.42.6, Kepler 0.12.0 | [8](08-stack-versions.md#summary) | [Tools](../tools/prometheus.md), [Kepler](../tools/kepler.md#metrics), [OpenTelemetry Demo](../tools/opentelemetry-demo.md) |
| Metric names in specs | `jaeger-query`, `kepler_container_*_joules_total`, demo 1.x names | Names of the current charts | [8](08-stack-versions.md#experimentstestyml), [11](11-current-stack-specs.md#metric-names) | [Kepler](../tools/kepler.md#metrics), [Experiment design](../experiment-design.md#responses) |
| Experiment specs | 30 s export specs leave `product-catalog` at 1 s | Fixed, every spec starts with a comment | [11](11-current-stack-specs.md#fix-in-the-30-s-export-specs) | [Experiment design](../experiment-design.md#the-specs-and-what-to-compare) |
| Repository layout | Values and dashboard in the root, helper scripts | `deployments/`, no helper scripts | [9](09-repository-layout.md#deployments), [3](03-deployment-section.md#removed-scripts), [4](04-api-server-proxy.md#the-cluster-proxy), [5](05-oxn-setup.md#the-command) | [Getting started](../getting-started.md) |
| Linting and formatting | None | Ruff and yamllint, pinned, checked in CI | [17](17-lint-and-format.md#ruff) | [Getting started](../getting-started.md#lint-and-format) |
| Type checking | None, an unused `[mypy]` section | ty on `oxn/` and `locust/`, pinned, checked in CI | [17](17-lint-and-format.md#ty) | [Getting started](../getting-started.md#type-check) |
| Documentation | One long README | Sphinx site with guides and tool pages, Material theme | [10](10-documentation-site.md#pages), [11](11-current-stack-specs.md#documentation), [15](15-material-theme.md#theme) | [Overview](../index.md) |

## Open limitations

What the changes so far leave open:

| Limitation | From |
|---|---|
| Three unit tests from GOXN fail: two `test_command_line` checks of the timeout and one `test_kubernetes_orchestration` case. | [1](01-package-layout.md#known-limitations), [18](18-formatting-and-type-fixes.md#known-limitations) |
| Ruff selects only a small set of rules, and `evaluation/` is not type checked. | [17](17-lint-and-format.md#known-limitations) |
| After an error or ctrl-c, in-cluster Locust pods and treatments are only removed with the SUE, so they stay with `--keep-sue`. | [16](16-refactorings.md#known-limitations) |

## Writing a change page

Add a page to this folder with every change to the code, the specs, the deployments or the tooling:

- **Name.** Number it after the last page, for example `16-short-name.md`, and title it `# 16. Short name`.
- **Lists.** Add it at the bottom of the [In order](#in-order) table and of the toctree at the top of this file. Update the [GOXN and now](#goxn-and-now) table if the change touches one of its areas, or add a row. Update [Open limitations](#open-limitations).
- **Perspective.** Compare to GOXN, not to the previous change, so each page reads on its own. Commit hashes and dates are not needed, the order is the number.

Each page uses the same structure:

1. **Compared to GOXN.** One line under the title that says what is different from GOXN after the change.
2. **Summary.** What the change does in a few sentences, and a table with GOXN and the state after the change.
3. **One section per part of the change.** A **Now documented in** line that links to the main docs, then what changed, **Why.** and, where users have to act, **What this breaks.**
4. **Known limitations.** What the change leaves open on purpose, with a status.

When a later change makes part of an older page wrong, leave the old text, add a short note that links to the newer page, and update the status of its known limitations.
