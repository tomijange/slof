# 3. A deployment section in the spec

**Compared to GOXN:** an experiment spec can deploy its own SUE and observability stack before each run and remove it afterwards, instead of a shell script running `helm` around `oxn`.

## Summary

In GOXN, `KubernetesOrchestrator.orchestrate()` and `teardown()` only logged "noop implementation". `run_experiment_suite.sh` installed and removed the stack around each `oxn` call. This change adds an optional `deployment` section to the spec, which `oxn` applies around every run. New commands deploy and remove it without running an experiment.

| | GOXN | After this change |
|---|---|---|
| SUE lifecycle | `run_experiment_suite.sh` runs `helm install` and deletes PVCs by name | A `deployment` section in the spec, applied by `oxn` |
| `orchestrate()` and `teardown()` on Kubernetes | Do nothing | Deploy and remove the `deployment` section |
| Run order on Kubernetes | Compile-time treatments, then `orchestrate()` | `orchestrate()`, then compile-time treatments |
| Deploy or remove by hand | `helm` commands from the README | `oxn deploy <spec>`, `oxn teardown <spec>` |
| Inspect the SUE after a run | Not possible, `oxn` tears it down | `--keep-sue` |
| Repeated runs | `run_multiple_experiments.sh` | `--times` |

## Section format

**Now documented in:** [Deployments: section format](../deployments.md#section-format)

The section is an ordered list of Helm releases and manifest folders, described by `DeploymentDescription` in the [spec model](02-typed-specs.md) and applied by `oxn/orchestration/deployment.py`:

```yaml
deployment:
  namespaces:
    - name: system-under-evaluation
  steps:
    - helm:
        release: astronomy-shop
        chart: opentelemetry-demo
        repo: https://open-telemetry.github.io/opentelemetry-helm-charts
        version: 0.42.6
        namespace: system-under-evaluation
        values: [deployments/values/values_opentelemetry_demo.yaml]
```

Specs without a `deployment` section work as before. They expect the SUE to be running already. `experiments/test.yml` is the only spec that has one after this change.

## What deploy and teardown do

**Now documented in:** [Deployments: what deploy and teardown do](../deployments.md#what-deploy-and-teardown-do)

- **Deploy** creates the namespaces the section owns, then runs each step: `helm upgrade --install --wait` for Helm steps, `kubectl apply` and optionally `kubectl rollout status` for manifests.
- **Teardown** runs the steps in reverse order. It also deletes the PVCs labelled `app.kubernetes.io/instance=<release>`, because Helm leaves PVCs from StatefulSets behind. Finally, it deletes the owned namespaces and waits until they are gone.

**Why.** In GOXN, the SUE lifecycle lived outside `oxn`. `run_experiment_suite.sh` switched the `kubectl` context namespace, ran `helm install` with versions and values files written into the script, and deleted Elasticsearch PVCs by fixed names such as `data-astronomy-shop-elasticsearch-data-0`. This had three problems:

- The setup of an experiment was split between the spec and the script.
- A single `oxn <spec>` call did not start from a known cluster state.
- The script broke as soon as a chart named things differently.

With the section in the spec, the spec alone says what an experiment runs on. Every run starts from a clean cluster, and teardown cleans up by label, not by name.

## Deploy and tear down by hand

**Now documented in:** [Deployments: deploy as part of an experiment](../deployments.md#deploy-as-part-of-an-experiment), [Deploy and tear down by hand](../deployments.md#deploy-and-tear-down-by-hand)

- `oxn deploy <spec>` and `oxn teardown <spec>` apply and remove the section without running an experiment. They fail if the spec has no `deployment` section.
- The Makefile wraps them as `make deploy-sue` and `make teardown-sue`, with `SPEC=<spec>` to choose another spec than `experiments/test.yml`.
- `--keep-sue` leaves the SUE running after the experiment, so you can inspect it. Remove it later with `oxn teardown <spec>`.

## Changed run order on Kubernetes

**Now documented in:** [Architecture: one experiment run](../architecture.md#one-experiment-run)

`Engine.run` now works in this order on Kubernetes:

1. Deploy the SUE.
2. Apply the compile-time treatments.
3. Check that the SUE is ready.
4. Create the load generator.

**Why.**

- **Compile-time treatments.** On Kubernetes they patch the running SUE and restart its pods, so the SUE has to exist first. With Docker Compose they change what gets built, so they still run before `orchestrate()`. Docker Compose is gone since [Removal of Docker Compose support](12-remove-docker-compose.md), so they now always run after it.
- **Load generator.** `LocustKubernetesLoadgenerator` resolves the address of its target when it is created, so it has to wait until after deployment.
- **Failures.** If deployment fails, the engine cleans up compile-time treatments and tears the SUE down before it re-raises, unless `--keep-sue` is set. Once deployment has succeeded, `main()` handles the teardown. Since [Refactorings](16-refactorings.md#engine-phases), `Engine.teardown()` handles every teardown, also of a failed or interrupted deployment.

## Removed scripts

`run_experiment_suite.sh` and `run_multiple_experiments.sh` are gone. The `deployment` section replaces the `helm` calls, and `--times` replaces the loop over repeated runs.

**What this breaks.** If you ran experiments through `run_experiment_suite.sh`, add a `deployment` section to each spec, or deploy the stack with `oxn deploy` and run the spec without one.

## Tests

`test_deployment.py` covers the section in the spec model, the commands deploy runs, teardown in reverse order, that the shipped deployment only references existing files, and the run order on Kubernetes and Docker Compose.

## Known limitations

| Limitation | Status |
|---|---|
| **Outdated specs.** The `recommendation_*` specs have no `deployment` section. They expect the stack that `run_experiment_suite.sh` used to install. | Resolved by [Specs for the current stack](11-current-stack-specs.md) |
| **`debug.yml`.** [Deployments](../deployments.md#shipped-setups) lists `experiments/debug.yml` as a second spec with a `deployment` section, but [Repository layout](09-repository-layout.md) removes that file. `test.yml` is the only one. | Resolved by [Specs for the current stack](11-current-stack-specs.md). Every spec has a `deployment` section, and [Deployments](../deployments.md) no longer lists `debug.yml` |
