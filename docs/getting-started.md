# Getting started

This guide takes you from a fresh checkout to a finished experiment on a Kubernetes cluster.

## Prerequisites

- Python 3.10 or newer
- `kubectl` with access to a cluster
- [Helm](https://helm.sh/docs/intro/install/)
- A cluster with real hardware energy counters, if you want Kepler data

Run every command from the repository root, because the paths in experiment specs are relative to it.

## Install oxn

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Use the editable install (`-e`). `oxn` loads its Locust templates from `locust/kubernetes/` in the checkout, so a regular `pip install .` fails when load generation starts.

Check that the install worked:

```bash
oxn --help
```

## Prepare the cluster

`oxn` acts on your current Kubernetes context, and teardown deletes namespaces. Check the context before you continue:

```bash
kubectl config current-context
```

Then run the setup guide:

```bash
oxn setup
```

It checks for `kubectl` and Helm, asks you to confirm the cluster and then goes through [OpenEBS](tools/openebs.md), [Prometheus](tools/prometheus.md) and [Kepler](tools/kepler.md). For each one it shows whether it is already there and the command it would run, and it asks before installing anything.

- `oxn setup --dry-run` only shows the state of the cluster and the commands, and changes nothing.
- `oxn setup --yes` installs what is missing without asking, for use in scripts.

`oxn setup` does not touch an existing install it did not expect. If OpenEBS is installed without the `openebs-hostpath` StorageClass, or Kepler runs in another namespace, it reports a conflict and exits with code 1, and you decide how to resolve it. It treats Prometheus as ready once the `ServiceMonitor` CRD exists, because experiment specs deploy the release themselves.

## Run an experiment

Run an experiment and write its report to `reports/`:

```bash
mkdir -p reports
oxn experiments/test.yml --report reports/
```

`oxn` deploys the SUE from the spec's `deployment` section before the run and removes it afterwards. See [Deployments](deployments.md).

`test.yml` runs for six minutes. Many `recommendation_*` specs run for more than an hour, and they need updating first. See [Shipped setups](deployments.md#shipped-setups).

`oxn` reaches the cluster through the Kubernetes API server, so it runs anywhere `kubectl` works. See [Reaching the cluster network](deployments.md#reaching-the-cluster-network).

## Run the tests

```bash
python -m pytest oxn/tests/unit/test_deployment.py oxn/tests/unit/test_installer.py
```

`make coverage` runs the whole test suite, but parts of it are out of date: several modules do not import and other tests fail. These two files cover the deployment code and the setup guide, and they pass.

## Lint and format

Ruff lints and formats the Python code and yamllint checks the YAML. Both are Python packages, as is the type checker below. Install them once, with the virtual environment active:

```bash
pip install -r requirements-dev.txt
```

`make lint` checks every file without changing it, the same check the Lint workflow runs on every push and pull request. `make format` fixes what Ruff can fix and formats the Python files. yamllint does not change files, so fix its findings by hand.

The settings are in `pyproject.toml` for Ruff and `.yamllint.yml` for yamllint. yamllint skips the Locust manifests in `locust/kubernetes/` that are Jinja templates or copies from another project, and allows one space inside braces, as in `{ name: prometheus }`.

### Commit hook

To run `make lint` before every commit, install the hook in `.githooks/` once:

```bash
make hooks
```

The hook uses `.venv/` even when it is not activated, so commits from an editor are checked too. A failing check stops the commit. Fix the findings, for example with `make format`, and commit again, or skip the check once with `git commit --no-verify`. The hook checks the files in the working tree, not only the staged changes.

## Type check

ty checks the type hints in `oxn/` and `locust/`. It is in `requirements-dev.txt` and runs as the last step of `make lint`. To run it on its own, with the virtual environment active:

```bash
ty check
```

ty reads the installed packages from the active virtual environment, so install `oxn` with `pip install -e .` first. Otherwise every import of `kubernetes`, `pandas` or `pydantic` is an error. The settings are under `[tool.ty]` in `pyproject.toml`: ty checks against Python 3.10, the oldest version `oxn` supports, and skips `evaluation/`, whose scripts and notebooks need packages that `oxn` does not install.

In VS Code, the [ty extension](https://marketplace.visualstudio.com/items?itemName=astral-sh.ty) shows the same findings while you type.
