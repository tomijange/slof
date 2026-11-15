# 17. Linting, formatting and type checking

**Compared to GOXN:** Ruff lints and formats the Python code, yamllint checks the YAML and ty checks the type hints, all pinned, with `make lint`, `make format` and a Lint workflow. GOXN had no linter, formatter or type checker, only an unused `[mypy]` section in `setup.cfg`. The repository no longer ships VS Code settings.

## Summary

This change adds the tools and their settings. Every contributor and the CI then check the same rules with the same versions. It does not format or fix any files yet. All tools are Python packages in `requirements-dev.txt`, so the repository needs no Node.js.

| Area | GOXN | After this change |
|---|---|---|
| Python | No linter or formatter | Ruff 0.17.5: pyflakes, the pycodestyle errors, import sorting, and Ruff's formatter with a line length of 120 |
| YAML | No checks | yamllint 1.38.0 |
| Types | An unused `[mypy]` section in `setup.cfg` | ty 0.0.104 on `oxn/` and `locust/`, against Python 3.10 |
| Commands | None | `make lint` checks, `make format` fixes |
| CI | None | `.github/workflows/lint.yml` installs `oxn` and the tools, then runs `make lint` on every push to `main` and every pull request |
| Editor settings | `.vscode/launch.json` and `.vscode/settings.json` | None, `.vscode/` is ignored |

## Ruff

**Now documented in:** [Getting started](../getting-started.md#lint-and-format)

`pyproject.toml` configures Ruff under `[tool.ruff]`. It selects `E4`, `E7`, `E9`, `F` and `I`: the pyflakes checks, the pycodestyle errors that are not about style, and import sorting. The rules are listed explicitly because Ruff's default selection changes between versions. Notebooks and the generated `oxn/_version.py` are excluded. `oxn/__init__.py` and `evaluation/evaluation.py` may import after code, because gevent has to patch the standard library first.

**Why.** Ruff is one fast tool for both linting and formatting, and the usual choice for Python projects. The selected rules find unused imports and variables and undefined names, which the refactorings so far left behind, without asking for a rewrite of GOXN's code style.

## yamllint

**Now documented in:** [Getting started](../getting-started.md#lint-and-format)

`.yamllint.yml` extends yamllint's default rules. It allows files without `---`, has no line length limit for the PromQL queries in the specs, allows lists under a key with or without indentation as long as a file is consistent, and allows commented-out entries at their own indentation. It skips the three Locust manifests `configmap.yaml`, `master.yaml` and `worker.yaml`, which `oxn` renders as Jinja templates.

**Why.** The specs and Helm values are YAML, and a typo there only shows when an experiment runs. yamllint finds syntax errors, duplicate keys and inconsistent indentation. It does not format, but no Python YAML formatter keeps comments and flow mappings reliably.

## ty

**Now documented in:** [Getting started](../getting-started.md#type-check)

`requirements-dev.txt` pins ty 0.0.104. `pyproject.toml` configures it under `[tool.ty]`: it checks against Python 3.10, the oldest version in `setup.cfg` and Ruff's target, and only checks `oxn/` and `locust/`. `make lint` runs `ty check` after the linters. The `[mypy]` section in `setup.cfg` is removed.

ty resolves every import against the installed packages, so the Lint workflow runs `pip install -e . -r requirements-dev.txt` instead of installing only the tools, and its pip cache also depends on `setup.cfg`.

**Why.** Ruff only finds names and imports. It cannot see a wrong argument type, a missing attribute or a method override with another signature. ty comes from the makers of Ruff, is fast enough to run with every lint, and installs with pip like the other tools. mypy skips the bodies of functions without type hints by default, and most of the GOXN code has few hints. ty checks those bodies with inferred types.

**What this breaks.** Run `pip install -e .` and `pip install -r requirements-dev.txt` once before `make lint` or `make format`. Without the dependencies of `oxn`, ty reports every import of `kubernetes`, `pandas` or `pydantic` as an error.

## Editor settings

`.vscode/launch.json` and `.vscode/settings.json` are removed, and `.gitignore` ignores `.vscode/`.

**Why.** The settings were one person's editor setup, not part of the project. The launch configuration still ran `experiments/debug.yml`, which [Repository layout](09-repository-layout.md#known-limitations) removed. The tools now carry the project's settings in `pyproject.toml` and `.yamllint.yml`, which every editor and the CI read. The [ty extension](https://marketplace.visualstudio.com/items?itemName=astral-sh.ty) for VS Code reads the ty settings.

**What this breaks.** Local `.vscode/` folders stay as they are and are no longer tracked. The debug configuration for `python -m oxn` is gone.

## Known limitations

| Limitation | Status |
|---|---|
| The repository does not pass `make lint` yet, so the Lint workflow fails. `make format` fixes most findings. Seven unused variables and the yamllint findings in `experiments/test.yml`, the Locust manifests and the Helm values need fixing by hand. | Open |
| ty finds 160 problems in `oxn/` and `locust/`. 64 of them are attributes on values that can be `None`, most of them fields of the Kubernetes client, such as `metadata.name`. Three are imports that no longer resolve since [Package layout](01-package-layout.md), in `oxn/loadgen/loadgen_config.py`, `oxn/tests/unit/test_loadgen.py` and `oxn/tests/unit/test_utils.py`. | Open |
| ty is still in beta, with 0.0.x versions. New versions can add or change rules, so the pin is updated by hand. | Open |
| `evaluation/` is not type checked. Its scripts and notebooks need packages such as `seaborn` and `scikit-learn` that `setup.cfg` does not install. | Open |
| Ruff selects only a small set of rules. More, such as `UP` or `B`, would find a few hundred places in the GOXN code. | Open |
| No tool checks the four JSON files, such as the Grafana dashboard. | Open |
