# 27. Deployment image treatment

**Compared to GOXN:** the compile-time treatment `deployment_image` changes the image of one container of a deployment, waits until every pod runs it, and changes it back on clean. An experiment can compare two implementations of a service, such as the Python recommendation service of the demo and a rewrite, with everything else the same.

## Summary

In GOXN, a treatment can scale, kill or slow down a service, but the service always runs the image its chart names. To compare implementations, the chart values have to be changed by hand for each run. This change adds a treatment for it and the orchestrator methods it needs. The image has to come from a registry the nodes can pull from.

| | GOXN | After this change |
|---|---|---|
| Changing the image of a service | Edit the chart values by hand, one spec per image | `deployment_image`, so a matrix level can select the image |
| Orchestrator methods | No image methods | `get_image` and `set_image` in the `Orchestrator` interface |
| Waiting for a changed pod template | `_wait_until_deployment_ready`, which counts ready pods | `is_rollout_done`, with the checks of `kubectl rollout status` |

## The treatment

**Now documented in:** [Experiments](../experiments.md#built-in-treatments)

`DeploymentImageTreatment` in `oxn/treatments/compile_time/deployment_image.py` has the action `deployment_image`. Its params extend `PodSelectorParams`:

| Param | Format | Default |
|---|---|---|
| `namespace`, `label_selector`, `label` | The deployment, as for the other treatments | |
| `image` | Image reference with tag or digest, at least one character | |
| `container` | Name of a container of the deployment | The first container of the pod template |

`inject` reads the current image, sets the new one and waits for the rollout. `clean` sets the image it read. If `inject` could not read the image, `clean` changes nothing. Errors of the orchestrator go to the treatment's messages, as in `scale_deployment`. The treatment only uses the interface, so it works with any orchestrator.

```yaml
treatments:
  - recommendation_rust:
      action: deployment_image
      params:
        namespace: system-under-evaluation
        label_selector: app.kubernetes.io/name
        label: recommendation
        container: recommendation
        image: slof.local/recommendation-rust:0.1.0
```

`TreatmentRegistry` lists the treatment, and `schema.json` has its params.

**Why.** A compile-time treatment runs after the deploy and before the load. So the image change happens before any data is recorded, and every variant deploys the same chart with the same values. Using a treatment instead of a values file keeps the swap to one place in the spec, which a matrix level can add or leave out.

## Orchestrator methods

**Now documented in:** [Architecture](../architecture.md#orchestrators)

The `Orchestrator` interface gets two workload methods:

| Method | Does |
|---|---|
| `get_image(workload, container=None)` | Returns the image of a container, by default the main container |
| `set_image(workload, image, container=None)` | Changes the image and waits until every copy of the workload runs it |

`KubernetesOrchestrator.set_image` sends a strategic merge patch with only the name and image of the container, so the steering sidecar and other containers stay as they are. A container name that the deployment does not have raises `OrchestratorResourceNotFoundException`, and so does a missing deployment.

After the patch, `_wait_until_rollout_done` polls `is_rollout_done` every 2 seconds for up to 300 seconds. If the rollout is not done by then, it raises an `OrchestratorException` that suggests checking the pods, for example for an image that cannot be pulled. `is_rollout_done` reads the deployment status and checks what `kubectl rollout status` checks:

- `observedGeneration` has reached `generation`, so the controller has seen the patch.
- `updatedReplicas` has reached `spec.replicas`.
- No old replicas are left.
- Every updated replica is available.

**Why.** `is_deployment_ready` compares ready replicas to all replicas. During a rolling update the old pods are still ready, so it can report ready before a single new pod runs. The load would then start partly on the old image. `_wait_until_deployment_ready` also only logs a warning after its timeout. For an image change, a rollout that does not finish usually means the image is missing, and the run should not measure that.

**What this breaks.** Other implementations of `Orchestrator` have to implement `get_image` and `set_image`.

## Tests

`oxn/tests/unit/test_orchestrator_interface.py` checks that:

- the treatment reads the image, sets the new one and sets the old one back, through the interface only,
- `clean` does nothing if the image could not be read,
- `get_image` reads the main container or a named one and rejects unknown names,
- `set_image` patches only the named container and waits for the rollout,
- `is_rollout_done` is false for an unobserved generation, missing updated replicas, old replicas or unavailable ones,
- the wait raises after its timeout.

`test_runner.py` lists `deployment_image` as compile-time, and `test_treatment_params.py` checks its params. `python -m pytest oxn/tests/unit` reports 269 passing tests and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists.

## Known limitations

| Limitation | Status |
|---|---|
| Only one container per treatment. Changing two needs two treatments, which roll out one after the other. | Open |
| The rollout timeout of 300 seconds is fixed, not a param. | Open |
| Other restarts, such as those of `prepare_network_faults` and `restart`, still wait with `_wait_until_deployment_ready` and only warn after its timeout. | Open |
| The treatment only changes the image. Environment variables, ports and probes stay as the chart sets them, so the new image has to accept them. | By design |
