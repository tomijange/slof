# 14. Removal of the setup scripts

**Compared to GOXN:** the `setup/` folder is gone. `oxn setup` prepares the cluster, and Getting started explains how to install `oxn` from a checkout.

## Summary

GOXN had four shell scripts in `setup/`. [`oxn setup`](05-oxn-setup.md#the-command) replaced the two that installed cluster tools with `oxn setup`. The two that were left only cloned a repository and created a virtual environment. This change removes them too, so `setup/` no longer exists.

| Area | GOXN | After this change |
|---|---|---|
| Cluster setup | `setup/1_setup_storage_provider.sh`, `setup/2_setup_kepler.sh` | `oxn setup` (since [change 5](05-oxn-setup.md#the-command)) |
| Installing `oxn` | `setup/3_setup_goxn.sh` clones GOXN and runs `pip install .` | [Getting started: install oxn](../getting-started.md#install-oxn): `pip install -e .` in a checkout |
| Replication package | `setup/X_setup_replication_package.sh` clones it and creates a venv | Linked from the README. Clone it yourself |

## Setup scripts

**Now documented in:** [Getting started: install oxn](../getting-started.md#install-oxn)

Removed:

- `setup/3_setup_goxn.sh`, which cloned GOXN into `goxn/`, created a `venv` and ran `pip install .`.
- `setup/X_setup_replication_package.sh`, which cloned the GOXN replication package into `goxn-replication-package/` and created a `venv` there.

**Why.** Apart from the `git clone`, both scripts repeated what the README and [Getting started](../getting-started.md) already explain. They had to be run from outside the repository they cloned, so they were of no use to someone who already has a checkout. The install script used `pip install .`, not the editable install that the docs recommend.

**What this breaks.** Nothing in the code or the docs called these scripts. If you used them, follow [Getting started: install oxn](../getting-started.md#install-oxn) instead.

## Known limitations

- The replication package belongs to GOXN. SLOF has none of its own yet.
