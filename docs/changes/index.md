# Changes

This fork builds on [GOXN](https://github.com/JulianLegler/goxn) by Julian Legler. This section lists every change since then, one page per change, and compares each one to GOXN. Read them in order: later pages build on earlier ones.

## In order

| # | Change | Compared to GOXN |
|---|---|---|
| 1 | [Package layout](01-package-layout.md) | Modules in packages by responsibility, absolute imports, entry point `oxn.cli.main:main` |
| 2 | [Typed experiment specs](02-typed-specs.md) | A pydantic spec model instead of `schema` and nested dicts. Unknown keys stop the run |
| 3 | [A deployment section in the spec](03-deployment-section.md) | Specs deploy and remove their own stack, `oxn deploy`, `oxn teardown`, `--keep-sue`. Compile-time treatments run after the deploy on Kubernetes |
| 4 | [Reaching the cluster through the API server proxy](04-api-server-proxy.md) | `oxn` runs anywhere `kubectl` works. Failed `tc` commands are logged |
| 5 | [`oxn setup`](05-oxn-setup.md) | One command installs OpenEBS, Prometheus and Kepler in order, instead of `setup/*.sh` |

## GOXN and now

What differs from GOXN today, by area. "Changed in" points to the change pages, "Documented in" to the pages that describe the current state.

| Area | GOXN | Now | Changed in | Documented in |
|---|---|---|---|---|
| Code layout | About 25 modules side by side in `oxn/` | Packages by responsibility | [1](01-package-layout.md#packages) | [Architecture](../architecture.md#packages) |
| Spec format | `schema` validation, unknown keys ignored | Typed pydantic model, unknown keys rejected | [2](02-typed-specs.md#the-spec-model) | [Experiments](../experiments.md#spec-structure) |
| SUE lifecycle | `run_experiment_suite.sh` runs `helm` by hand, `orchestrate()` and `teardown()` do nothing on Kubernetes | A `deployment` section in the spec, `oxn deploy` and `oxn teardown` | [3](03-deployment-section.md#what-deploy-and-teardown-do) | [Deployments](../deployments.md) |
| Run order on Kubernetes | Compile-time treatments, then deploy | Deploy, then compile-time treatments | [3](03-deployment-section.md#changed-run-order-on-kubernetes) | [Architecture](../architecture.md#one-experiment-run) |
| Cluster access | Direct HTTP to pod and cluster IPs, `oxn` inside the cluster network | Kubernetes API server proxy | [4](04-api-server-proxy.md#the-cluster-proxy) | [Deployments](../deployments.md#reaching-the-cluster-network) |
| Cluster setup | `setup/*.sh` and README commands | `oxn setup` | [5](05-oxn-setup.md#the-command) | [Getting started](../getting-started.md#prepare-the-cluster) |
| Repository layout | Values and dashboard in the root, helper scripts | `deployments/`, no helper scripts | [3](03-deployment-section.md#removed-scripts), [4](04-api-server-proxy.md#the-cluster-proxy), [5](05-oxn-setup.md#the-command) | [Getting started](../getting-started.md) |

## Open limitations

What the changes so far leave open:

| Limitation | From |
|---|---|
| The `recommendation_*` specs have no `deployment` section and use the old service and metric names. `experiments/test.yml` is the only spec kept up to date. | [3](03-deployment-section.md#known-limitations) |
| Several unit tests from GOXN fail or do not import. | [1](01-package-layout.md#known-limitations) |
| [Deployments](../deployments.md#shipped-setups) lists `experiments/debug.yml`, which was removed. | [3](03-deployment-section.md#known-limitations) |

## Writing a change page

Add a page to this folder with every change to the code, the specs, the deployments or the tooling:

- **Name.** Number it after the last page, for example `11-short-name.md`, and title it `# 11. Short name`.
- **Lists.** Add it at the bottom of the [In order](#in-order) table and of the toctree below. Update the [GOXN and now](#goxn-and-now) table if the change touches one of its areas, or add a row. Update [Open limitations](#open-limitations).
- **Perspective.** Compare to GOXN, not to the previous change, so each page reads on its own. Commit hashes and dates are not needed, the order is the number.

Each page uses the same structure:

1. **Compared to GOXN.** One line under the title that says what is different from GOXN after the change.
2. **Summary.** What the change does in a few sentences, and a table with GOXN and the state after the change.
3. **One section per part of the change.** A **Now documented in** line that links to the main docs, then what changed, **Why.** and, where users have to act, **What this breaks.**
4. **Known limitations.** What the change leaves open on purpose, with a status.

When a later change makes part of an older page wrong, leave the old text, add a short note that links to the newer page, and update the status of its known limitations.

```{toctree}
:hidden:

01-package-layout
02-typed-specs
03-deployment-section
04-api-server-proxy
05-oxn-setup
```
