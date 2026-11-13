# 1. Package layout

**Compared to GOXN:** the modules of `oxn/` live in packages by responsibility instead of side by side, and all imports are absolute.

## Summary

GOXN kept about 25 modules at the top level of `oxn/`, with relative imports. This change sorts them into packages that match their role during an experiment run. Behaviour does not change. Only module paths, the entry point and the imports that depend on them do.

| | GOXN | After this change |
|---|---|---|
| Layout | All modules in `oxn/` | `cli`, `core`, `orchestration`, `loadgen`, `observability`, `reporting`, `common` |
| Imports | Relative, such as `from .store import ...` | Absolute, such as `from oxn.reporting.store import ...` |
| Entry point | `oxn.main:main` | `oxn.cli.main:main` |

## Packages

**Now documented in:** [Architecture: packages](../architecture.md#packages)

| Package | Modules moved there |
|---|---|
| `oxn/cli/` | `main.py`, `argparser.py` |
| `oxn/core/` | `engine.py`, `runner.py`, `treatments.py`, `validation.py`, `context.py` |
| `oxn/orchestration/` | `kubernetes_orchestrator.py`, `docker_orchestration.py` |
| `oxn/loadgen/` | `locust_kubernetes.py`, `config_load_generator.py`, `file_load_generator.py`, `loadgen_config.py` |
| `oxn/observability/` | `prometheus.py`, `jaeger.py`, `observer.py`, `responses.py` |
| `oxn/reporting/` | `report.py`, `store.py`, `pricing.py` |
| `oxn/common/` | `errors.py`, `log.py`, `settings.py`, `utils.py` |

`oxn/models/` and `oxn/steering/` stay where they were. Modules added by later changes go into these packages: `cli/installer.py` ([`oxn setup`](05-oxn-setup.md)), `orchestration/deployment.py` ([A deployment section in the spec](03-deployment-section.md)) and `orchestration/cluster_proxy.py` ([Reaching the cluster through the API server proxy](04-api-server-proxy.md)).

**Why.** The fork adds features on top of the engine. With every module in one folder, it was hard to see what belongs to orchestration and what belongs to observation. The packages make that clear, and new modules have an obvious home.

## What this breaks

- **Entry point.** The `oxn` command now calls `oxn.cli.main:main`, set in `setup.cfg` and `oxn/__main__.py`. Reinstall with `pip install -e .` after updating.
- **Imports.** Code that imports from GOXN must use the new paths. `evaluation/evaluation.py` now imports `oxn.reporting.store`, for example.
- **Locust templates.** `locust_kubernetes.py` moved one level deeper, so it now finds its templates at `../../locust/kubernetes`.

## Known limitations

| Limitation | Status |
|---|---|
| **Stale tests.** Some unit tests from GOXN fail after this change set: `test_jaeger`, `test_prometheus`, `test_treatments`, `test_command_line` and `test_kubernetes_orchestration`. `test_loadgen`, `test_orchestration` and `test_utils` do not import. Their imports were updated to the new paths, but their contents were not. | Open |
