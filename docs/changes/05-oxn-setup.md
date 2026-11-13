# 5. `oxn setup`

**Compared to GOXN:** `oxn setup` installs the tools that stay on the cluster between experiments, in the right order, instead of shell scripts and commands copied from the README.

## Summary

GOXN prepared a cluster with `setup/1_setup_storage_provider.sh`, `setup/2_setup_kepler.sh` and the install commands in its README. This change replaces them with an interactive command that checks what is already installed and asks before changing anything.

| | GOXN | After this change |
|---|---|---|
| Prepare a cluster | `setup/*.sh` and README commands | `oxn setup`, or `make setup-cluster` |
| Order | Up to the reader | OpenEBS, kube-prometheus-stack, Kepler |
| Already installed tools | Not checked, `helm install` fails on an existing release | Detected and skipped |
| Chart versions | Old OpenEBS manifest, kube-prometheus-stack 62.5.1, Kepler from the old Helm repo | OpenEBS 4.6.2, kube-prometheus-stack 92.16.1, Kepler 0.12.0 |

## The command

**Now documented in:** [Getting started: prepare the cluster](../getting-started.md#prepare-the-cluster), [Overview: install order](../index.md)

`oxn/cli/installer.py` walks through three tools, in the order they depend on each other:

1. **OpenEBS** 4.6.2, as the default `openebs-hostpath` StorageClass.
2. **kube-prometheus-stack** 92.16.1.
3. **Kepler** 0.12.0. It is skipped if Prometheus is not on the cluster.

Before it changes anything, it checks that `kubectl` and `helm` are installed, that it runs from the repository root, and that the cluster answers. It names the current `kubectl` context and asks whether to install into that cluster, defaulting to no. For each tool, it then shows what is already on the cluster and the exact command it would run, and asks before installing. Without a terminal to ask on, it treats the answer as no.

| Option | Effect |
|---|---|
| `--dry-run` | Only report what is installed and what would run |
| `--yes` | Install everything that is missing without asking, for scripts |

The tool definitions reuse `HelmRelease` from the [deployment section](03-deployment-section.md) of the spec model. `oxn setup` logs at `warning` by default, so its interactive output stays readable.

**Why.** The old scripts were not idempotent and used outdated charts. They also left it to the reader to get the order right: Kepler's `ServiceMonitor` needs the CRD that kube-prometheus-stack installs. Specs can deploy and remove Prometheus on every run, but the CRD stays, which is why Prometheus is part of setup.

**What this breaks.** `setup/1_setup_storage_provider.sh` and `setup/2_setup_kepler.sh` are removed. Use `oxn setup` instead.

## Tests

`test_installer.py` covers the install order, the questions, skipping what is already there, repairing a failed release, `--dry-run`, and stopping when a tool, the repository or the cluster is missing.

## Known limitations

Nothing is left open by this change.
