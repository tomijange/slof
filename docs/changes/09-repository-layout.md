# 9. Repository layout

**Compared to GOXN:** Helm values and the Grafana dashboard live in `deployments/`, scripts that the earlier changes replaced are gone, and the Makefile has targets for the new commands.

## Summary

GOXN kept its values files and dashboard in the repository root, next to several helper scripts. This change gathers the deployment inputs in one folder and removes what the other changes made obsolete.

| | GOXN | After this change |
|---|---|---|
| Helm values | `values_*.yaml` in the repository root | `deployments/values/` |
| Kepler dashboard | `kepler_dashboard.json` in the root | `deployments/dashboards/kepler_dashboard.json` |
| Helper scripts | `forward.ps1`, `run_experiment_suite.sh`, `run_multiple_experiments.sh`, `setup/*.sh` | Removed |
| Makefile | `coverage`, `build`, `clean` | Also `docs`, `setup-cluster`, `deploy-sue`, `teardown-sue` |

## `deployments/`

**Now documented in:** [Deployments: shipped setups](../deployments.md#shipped-setups), [Grafana: add the Kepler dashboard](../tools/grafana.md#add-the-kepler-dashboard), [Architecture: files read at runtime](../architecture.md#files-read-at-runtime)

- `deployments/values/` holds the values for every chart: kube-prometheus-stack (also the Istio variant), Istio, Kepler and the OpenTelemetry Demo with its persistence and local variants.
- `deployments/dashboards/` holds the Kepler Grafana dashboard.

Specs and `oxn setup` reference these paths, so `oxn` has to run from the repository root.

**Why.** With [deployment sections](03-deployment-section.md) in the specs, the values files are inputs that `oxn` reads, not just examples for the README. One folder makes it clear what a spec can reference.

## Removed files

| File | Replaced by |
|---|---|
| `run_experiment_suite.sh`, `run_multiple_experiments.sh` | The `deployment` section and `--times`, see [A deployment section in the spec](03-deployment-section.md#removed-scripts) |
| `forward.ps1` | The API server proxy, see [Reaching the cluster through the API server proxy](04-api-server-proxy.md) |
| `setup/1_setup_storage_provider.sh`, `setup/2_setup_kepler.sh` | `oxn setup`, see [`oxn setup`](05-oxn-setup.md) |
| `experiments/debug.yml` | `experiments/test.yml`, the spec kept up to date |
| The `evaluation` configuration in `.vscode/launch.json` | Nothing. It ran the evaluation on one fixed report file |

## Makefile

**Now documented in:** [Getting started](../getting-started.md), [Deployments: deploy and tear down by hand](../deployments.md#deploy-and-tear-down-by-hand)

| Target | Runs |
|---|---|
| `docs` | A strict Sphinx build, see [Documentation site](10-documentation-site.md) |
| `setup-cluster` | `oxn setup` |
| `deploy-sue` | `oxn deploy $(SPEC)`, with `SPEC` defaulting to `experiments/test.yml` |
| `teardown-sue` | `oxn teardown $(SPEC)` |

`clean` also removes `docs/_build/`.

## `.gitignore`

- **Removed:** entries for GOXN's old experiment and report folders (`irrera_*`, `performance_*`, `visibility_*`), `evaluation.py`, `oxn.wpr`, `.vagrant` and `kubevpn.exe`.
- **Added:** `.venv/`, `venv/`, `*.log` and `docs/_build/`.
- **Fixed:** `.pytest-cache` is now spelled `.pytest_cache`.

## Known limitations

| Limitation | Status |
|---|---|
| **`debug.yml` in the docs.** [Deployments](../deployments.md#shipped-setups) still lists `experiments/debug.yml` as a shipped setup. | Open |
| **`debug.yml` in `.vscode/launch.json`.** The remaining debug configuration still runs `experiments/debug.yml`. | Open |
