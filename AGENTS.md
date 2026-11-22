# AGENTS.md

Instructions for coding agents working in this repository. Humans should start with [README.md](README.md) and [docs/](docs/).

## Project

SLOF is a framework for experiment-driven evaluation of trade-offs between SLOs and sustainability. It is a fork of [GOXN](https://github.com/JulianLegler/goxn), which builds on OXN. The Python package and CLI are still called `oxn`.

- Text that describes the project says **SLOF**. Text that compares to the baseline says **GOXN**.
- New features belong in the Python engine and the experiment spec (YAML), not in standalone shell scripts.
- Kubernetes is the only orchestrator. Docker Compose support was removed.

## Layout

| Path | Contents |
|---|---|
| `oxn/` | The engine: `cli/`, `core/`, `models/`, `treatments/`, `orchestration/`, `loadgen/`, `observability/`, `reporting/`, `common/`, `steering/` |
| `oxn/tests/unit/` | Unit tests, no cluster needed |
| `oxn/tests/integration/` | Need a running cluster with Prometheus and Jaeger, fail without one |
| `experiments/` | Experiment specs |
| `deployments/` | Helm values and the Grafana dashboard |
| `locust/` | Locust scenarios and their data |
| `docs/` | Sphinx site (MyST Markdown, Material theme) |
| `schema.json` | JSON schema of the spec, generated |
| `evaluation/` | Notebooks and scripts, excluded from lint and type checks |

[docs/architecture.md](docs/architecture.md) walks through one run module by module. Read it before changing the engine.

Do not edit:

- `build/`, `oxn.egg-info/`: stale build output with an older module layout.
- `store.h5`, `trie.pickle`, `reports/`: experiment results, gitignored.
- `oxn/_version.py`: generated.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e . -r requirements-dev.txt
```

Python 3.10 is the oldest supported version. Do not use syntax or standard library features newer than that.

## Checks

Run these before you call a change done:

```bash
make lint                 # ruff check, ruff format --check, yamllint --strict, ty check (as in CI)
python -m pytest oxn/tests/unit
```

- `make format` fixes what Ruff can. Fix yamllint findings by hand.
- Three unit tests from GOXN fail on `main`: `test_command_line` (`test_it_accepts_timeout`, `test_it_has_default_timeout`) and `test_kubernetes_orchestration` (`test_it_checks_all_required`). Do not count them as regressions, and do not "fix" them on the side.
- After changing the spec model in `oxn/models/` or any treatment's params, run `make schema` and commit the updated `schema.json`. `test_schema.py` fails when it is out of date, and CI does not run the tests.
- After changing docs, run `make docs` (Sphinx with `-W`). MyST does not always warn on broken heading anchors, so check links to `#anchors` by hand.

Do not run experiments (`oxn <spec>`), `oxn setup`, `oxn deploy` or `oxn teardown` unless asked. They install and remove things on whichever cluster the current kube context points to.

## Code conventions

- Ruff with line length 120. The rule set is small (`E4`, `E7`, `E9`, `F`, `I`), so follow the style of the surrounding code beyond it.
- Type-hint new code. `ty` checks `oxn/` and `locust/`.
- `oxn/__init__.py` patches the standard library with gevent and must stay first.
- Specs are parsed into pydantic models (`oxn/models/experiment_spec.py`). Validate new spec fields and treatment params in the model, so a bad spec fails before anything is deployed.
- A treatment lives in `oxn/treatments/runtime/` or `oxn/treatments/compile_time/`, declares `action` and a `Params` model, and goes through the `Orchestrator` interface in `oxn/models/orchestrator.py`. Subclass `KubernetesTreatment` only when it really needs Kubernetes objects.
- Raise `OxnException` subclasses from `oxn/common/errors.py` with a readable message. Do not use `assert` for runtime checks.
- Use module loggers (`logging.getLogger(__name__)`), not the root logger.
- Paths in a spec resolve against the spec's folder.
- The YAML has no `---` document start and writes flow mappings as `{ key: value }`.

## Change pages

Every change to code, specs, deployments or tooling needs a page in `docs/changes/`, written in the same piece of work. Follow "Writing a change page" in [docs/changes/index.md](docs/changes/index.md):

- Number it after the last page (`NN-short-name.md`, title `# N. Short name`) and add it to the toctree and the "In order" table.
- Compare to GOXN, not to the previous change. No commit hashes or dates.
- Start with a **Compared to GOXN** line, then a summary with a GOXN vs. now table, one section per part with a **Now documented in** line linking to the main docs, and **Known limitations**.
- Update the "GOXN and now" and "Open limitations" tables in the index.
- When a change makes an older page wrong, keep the old text, add a note linking to the new page, and update its limitation status.
- Update the main docs (`architecture.md`, `experiments.md`, `deployments.md`, `getting-started.md`, `experiment-design.md`, `tools/`) as well, not only the change page.

## Writing style

Docs, docstrings and commit messages use short, plain sentences. Say what something does and why. Avoid filler, marketing words and hedging.

## Commits

Only commit when asked. Use Conventional Commits with a lowercase, imperative subject:

```
feat: resolve paths in a spec against the folder of the spec file

<What was wrong or missing before, in a few sentences.>

- <One bullet per part of the change>
- Add change page 26

Breaking
- <What users have to change, if anything>
```

Types in use: `feat`, `refactor`, `fix`, `docs`, `chore`, `style`. Do not add `Co-Authored-By` trailers or any other AI attribution to commits or pull requests.
