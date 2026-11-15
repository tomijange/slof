# 20. Orchestrator interface

**Compared to GOXN:** treatments act on the SUE through a generic `Orchestrator` interface instead of Kubernetes objects, so a second orchestrator, such as Docker Compose, can run them unchanged. Only `empty_kubernetes` and `security_context_kubernetes` are tied to Kubernetes. The steering sidecar lives in `oxn/steering/`, not in the orchestrator. `KubernetesOrchestrator` has no unused methods, one pair of methods for manifests instead of six, and error messages instead of asserts.

## Summary

In GOXN the `Orchestrator` base class only covered deploying the SUE and finding addresses. Treatments checked `get_orchestrator_type() == "kubernetes"`, cast the orchestrator to `KubernetesOrchestrator` and called its methods with `V1Deployment` and `V1Pod` objects. The Docker treatments bypassed the orchestrator and called the Docker daemon. [Change 12](12-remove-docker-compose.md) removed Docker Compose. This change describes what treatments need from an orchestrator, so that Compose can come back as one more implementation of the interface instead of a second set of treatments. It also cleans up `oxn/orchestration/kubernetes_orchestrator.py`, which shrinks from about 1150 to about 700 lines.

| | GOXN | After this change |
|---|---|---|
| What treatments call | `KubernetesOrchestrator` methods with `V1Deployment` and `V1Pod` | `Orchestrator` methods with a `WorkloadSelector` |
| Orchestrator check | `_validate_orchestrator()` in every treatment, comparing `get_orchestrator_type()` | Passes by default. `KubernetesTreatment` rejects other orchestrators. `get_orchestrator_type` removed |
| Kubernetes-only treatments | All | `empty_kubernetes`, `security_context_kubernetes` |
| Steering sidecar | Patched in by `KubernetesOrchestrator.patch_deployment_to_include_steering_sidecar_container`, called by each network treatment | `SteeringController.add_sidecar`, called by `KubernetesOrchestrator.prepare_network_faults` |
| Network treatments | Three copies of the same preconditions, inject and clean | One base class, `NetemTreatment` |
| Restart after a Prometheus or collector change | In the treatment, with a hard-coded deployment selector | In the orchestrator |
| Treatment class names | `Kubernetes…Treatment` | Without `Kubernetes` for treatments that work with any orchestrator. Actions unchanged |
| Pods and services of the whole cluster | Listed on init and, since [change 3](03-deployment-section.md), again after the deploy, never read | Not listed |
| Locust manifests | `deploy_deployment_yaml`, `deploy_configmap_yaml`, `deploy_service_yaml` and three `delete_…_yaml` | `deploy_yaml` and `delete_yaml`, by the manifest's `kind` |
| Prometheus and collector ConfigMaps | Read, parsed and written in four copies of the same code | `_read_configmap_yaml` and `_write_configmap_yaml` |
| Optional fields of Kubernetes objects | An `assert` per field and access, 48 in the orchestrator and 10 in `SteeringController` | Three helpers in `oxn/orchestration/kubernetes_objects.py`, no asserts |

## The orchestrator interface

**Now documented in:** [Architecture](../architecture.md#orchestrators)

`oxn/models/orchestrator.py` defines everything the engine, load generators, observability clients and treatments use:

| Group | Methods |
|---|---|
| Lifecycle | `orchestrate`, `ready`, `teardown` |
| Addresses | `get_address_for_service`, `get_prometheus_address`, `get_jaeger_address` |
| Workloads | `get_instances`, `kill_instance`, `get_replicas`, `scale`, `restart`, `is_ready`, `get_environment_variable`, `set_environment_variable` |
| Network faults | `prepare_network_faults`, `set_network_delay`, `set_network_loss`, `set_network_corruption`, `remove_network_faults` |
| Telemetry configuration | `get_prometheus_scrape_values`, `set_prometheus_scrape_values`, `get_otel_collector_probabilistic_sampling_values`, `set_otel_collector_probabilistic_sampling_values` |

`oxn/models/workload.py` holds the two types these methods take:

- `WorkloadSelector`: a namespace, a label key and a value. On Kubernetes it selects a deployment. In Compose it would select a service, with the project as namespace and a container label such as `com.docker.compose.service`.
- `WorkloadInstance`: one running copy, with its name, namespace, state and whether it runs. On Kubernetes it is a pod.

`PodSelectorParams.workload` builds the selector from a treatment's `namespace`, `label_selector` and `label`, so treatments pass `self.params.workload`. Methods that change a workload raise an `OrchestratorException` instead of returning `False` or `None`.

`translate_container_names`, a no-op, and `get_orchestrator_type`, which only the treatments' orchestrator check called, are removed from the interface and from `KubernetesOrchestrator`.

`KubernetesOrchestrator` implements the interface with its existing Kubernetes methods, which stay public for Kubernetes-only code: `get_deployment`, `get_pods`, `kill_pod`, `scale_deployment`, `restart_pods_of_deployment`, `is_deployment_ready`, `apply_security_context_to_deployment`, plus the new `get_workload_deployment` and `pods_of_deployment`. `set_deployment_env_parameter` and `get_deployment_env_parameters` are replaced by the interface methods. The SUE namespace, the ConfigMap names and keys and the selectors of the SUE's Prometheus and collector are constants at the top of `kubernetes_orchestrator.py` instead of literals in the treatments.

**Why.** Every operation the treatments use also exists in Docker Compose: killing, scaling and restarting containers, changing environment variables, running `tc` in a container's network namespace and rewriting a mounted configuration file. Describing them once lets the treatments stay as they are when a Compose orchestrator is added.

**What this breaks.** Own treatments that call `KubernetesOrchestrator` methods keep working if they subclass `KubernetesTreatment`, see [Treatments](#treatments). Code that called `set_deployment_env_parameter`, `get_deployment_env_parameters` or `patch_deployment_to_include_steering_sidecar_container` uses the interface methods instead.

## Steering sidecar

**Now documented in:** [Architecture](../architecture.md#orchestrators)

The sidecar is Kubernetes-only, so everything about it moved to `SteeringController` in `oxn/steering/steering_controller.py`:

- `SIDECAR_CONTAINER_NAME` and `SIDECAR_IMAGE`, before `OXN_SIDECAR_CONTAINER_NAME` and a literal in the orchestrator.
- `has_sidecar(deployment)` and `add_sidecar(deployment)`, before `patch_deployment_to_include_steering_sidecar_container`. `add_sidecar` returns `False` if the container is already there. `KubernetesOrchestrator.prepare_network_faults` waits for the deployment only when it was patched.
- `remove_netem(pods, interface)` replaces `remove_network_delay`, `remove_network_loss` and `remove_network_corruption`, which all sent `tc qdisc del dev <interface> root netem`.
- Failed requests raise an `OrchestratorException` instead of an `ApiException`. Before, the controller's handlers only caught `OrchestratorException`, so they never ran.

`SteeringController` no longer takes the unused `kube_client`. `KubernetesOrchestrator` waits for a deployment after a restart and after adding the sidecar with one helper, `_wait_until_deployment_ready`, which logs a warning if the deployment is still not ready instead of reporting it ready.

**Why.** The orchestrator decides how network faults reach a workload. On Kubernetes that is the sidecar, while a Compose orchestrator could run `tc` with `docker exec` or in a helper container. Keeping the sidecar in `oxn/steering/` keeps it out of the interface.

## Treatments

**Now documented in:** [Experiments](../experiments.md#own-treatments)

`Treatment._validate_orchestrator()` is no longer abstract and returns `True`, because treatments that only use the interface work with any orchestrator. `_orchestrator_is_one_of` is removed. `KubernetesTreatment` in `oxn/treatments/kubernetes.py` is the base class for treatments that change Kubernetes resources directly. It rejects other orchestrators when the treatment is built, with the message `<name> treatment is only supported for Kubernetes orchestrators`. Its `kubernetes` property returns the orchestrator typed as `KubernetesOrchestrator`. It is combined with `RuntimeTreatment` or `CompileTimeTreatment`, with `KubernetesTreatment` first.

| Action | Class before | Class now | Orchestrators |
|---|---|---|---|
| `empty` | `EmptyTreatment` | `EmptyTreatment` | Any |
| `empty_kubernetes` | `EmptyKubernetesTreatment` | `EmptyKubernetesTreatment` | Kubernetes |
| `delay` | `KubernetesNetworkDelayTreatment` | `NetworkDelayTreatment` | Any |
| `kubernetes_loss` | `KubernetesNetworkPacketLossTreatment` | `PacketLossTreatment` | Any |
| `kubernetes_corrupt` | `KubernetesCorruptPacketTreatment` | `PacketCorruptionTreatment` | Any |
| `kubernetes_kill` | `KubernetesKillTreatment` | `KillTreatment` | Any |
| `scale_deployment` | `DeploymentScaleTreatment` | `DeploymentScaleTreatment` | Any |
| `kube_probl` | `KubernetesProbabilisticHeadSamplingTreatment` | `ProbabilisticHeadSamplingTreatment` | Any |
| `kubernetes_otel_metrics_interval` | `KubernetesMetricsExportIntervalTreatment` | `MetricsExportIntervalTreatment` | Any |
| `kubernetes_prometheus_interval` | `KubernetesPrometheusIntervalTreatment` | `PrometheusIntervalTreatment` | Any |
| `security_context_kubernetes` | `KubernetesApplySecurityContextTreatment` | `KubernetesApplySecurityContextTreatment` | Kubernetes |

`security_context_kubernetes` patches the security context of a pod template, which only Kubernetes has. `empty_kubernetes` exists to fail with other orchestrators.

`delay`, `kubernetes_loss` and `kubernetes_corrupt` share `NetemTreatment` in `oxn/treatments/runtime/netem.py`. It prepares the workload in `preconditions`, applies the fault and waits for `duration` in `inject`, and removes it in `clean`. A subclass only implements `_apply`. All three now behave as `delay` and the `clean` of `kubernetes_loss` did before: a failure while applying or removing the fault is logged and the run continues. Before, an error in `inject` of `kubernetes_loss` or `kubernetes_corrupt`, or in `clean` of `delay` or `kubernetes_corrupt`, stopped the run.

Smaller differences:

| Treatment | Before | Now |
|---|---|---|
| `kube_probl` | `preconditions` raised an `OrchestratorException` if the ConfigMap was missing | Returns `False` with the message |
| `kubernetes_otel_metrics_interval` | Re-read the deployment with `app.kubernetes.io/name=<deployment name>` before patching it, whatever the spec's selector | Re-reads it with the spec's selector |
| `kubernetes_kill`, `scale_deployment` | A missing deployment or pod raised, because `OrchestratorResourceNotFoundException` is not an `OrchestratorException` | Recorded in the treatment's messages |
| `scale_deployment` | Failed an assertion for a deployment without `replicas` in its spec | Reads a missing value as 1, as Kubernetes does |
| Network faults on a deployment without pods | Failed an assertion | Raise `OrchestratorResourceNotFoundException` |

The action keys keep their names, so all specs in `experiments/` run unchanged.

**Why.** A class name with `Kubernetes` in it would be wrong once a second orchestrator runs it. The names now match the GOXN Docker treatments that [change 12](12-remove-docker-compose.md#treatments) removed, `KillTreatment`, `PacketLossTreatment` and `PrometheusIntervalTreatment`, which these classes can replace.

**What this breaks.** Code that imports the old class names imports the new ones. Own treatments that called `self._orchestrator_is_one_of(["kubernetes"])` subclass `KubernetesTreatment` instead.

## Load generators

`FileLoadGenerator` no longer asserts a `KubernetesOrchestrator` when the spec has a `target`, because it only calls `get_address_for_service`. `LocustKubernetesLoadgenerator` still asserts it, since it deploys Locust as Kubernetes manifests. `Prometheus` and `Jaeger` still use the API server proxy for a `KubernetesOrchestrator` and the address from the interface otherwise, as since [change 4](04-api-server-proxy.md#the-cluster-proxy).

## Cleanup of the Kubernetes orchestrator

**Now documented in:** [Architecture](../architecture.md#orchestrators)

### Removed methods and state

`list_of_all_pods` and `list_of_all_services` listed every pod and service of the cluster with two API calls, which on a busy cluster are the largest responses `oxn` requests. Nothing read them. `execute_console_command_on_all_matching_pods` ran a command in the first container of the first matching pod through `kubectl exec` and printed its exit status. No treatment called it since the network treatments use the steering sidecar. `configmap_name`, an optional parameter of `get_prometheus_scrape_values` and `set_prometheus_scrape_values` that no caller passed, is gone too. The two tests in `test_kubernetes_orchestration.py` that read `list_of_all_pods` and `list_of_all_services` are removed with them.

**What this breaks.** Own code that called one of these methods. `execute_console_command_on_all_matching_pods` can be replaced with `kubernetes.stream.stream` and `kube_client.connect_get_namespaced_pod_exec`, which it used.

### Manifests

`deploy_yaml(yaml_str)` creates the Deployment, ConfigMap or Service a manifest describes. If one with the same name exists, it deletes it and creates it again, as each of the three `deploy_…_yaml` methods did. `delete_yaml(yaml_str)` deletes it. Other kinds raise an `OrchestratorException`. `LocustKubernetesLoadgenerator` deploys and deletes its four manifests in a loop.

**What this breaks.** Callers of the six old methods call `deploy_yaml` or `delete_yaml`.

### ConfigMaps of the SUE

`_read_configmap_yaml(name, key)` reads a ConfigMap in `system-under-evaluation` and parses the YAML file under `key`. `_write_configmap_yaml` writes it back. The four methods for the Prometheus scrape values and the collector's sampler use them. A missing ConfigMap or key raises an `OrchestratorException` that names both, instead of `relay.yaml not found in ConfigMap`.

### Asserts

The models of the Kubernetes client declare nearly every field optional, so each access to `metadata.name`, `spec.template.spec` or `status` was preceded by an `assert` for ty. Most methods began with four to six of them, and some asserted parameters that cannot be `None`. `oxn/orchestration/kubernetes_objects.py` replaces them:

| Helper | Returns | Raises an `OrchestratorException` if |
|---|---|---|
| `name_and_namespace(obj)` | Name and namespace of a deployment, pod, service or ConfigMap | The metadata lacks either |
| `pod_containers(deployment)` | The containers of the pod template | The deployment has no pod template |
| `pod_selector(deployment)` | `matchLabels` as a label selector string | The deployment has no `matchLabels`, which as an empty selector would match every pod of the namespace |

Where a missing field has an obvious meaning, the code uses it: a deployment without status is not ready, a service without spec has no cluster IP, a ConfigMap without data has no key. `_services()` raises an `OrchestratorException` if the spec has no `experiment.services`, which Prometheus and Jaeger need. `scale_deployment` patches only `spec.replicas` of the scale subresource instead of sending the whole deployment. `apply_security_context_to_deployment` logs errors instead of printing them.

**Why.** An assert gives no message, disappears with `python -O` and hides the one check that matters among the ones that only satisfy the type checker. The integration tests in `oxn/tests/integration/test_validation.py`, whose spec has no `experiment.services`, now stop with that message as an error instead of a failed assertion.

## Tests

`oxn/tests/unit/test_orchestrator_interface.py` checks that:

- only the two Kubernetes treatments reject an orchestrator that only has the interface's methods,
- the network and kill treatments use only interface methods,
- `KubernetesOrchestrator` adds the sidecar once, maps pods to instances and reads and writes environment variables of the first container,
- manifests are deployed by kind and replaced if they exist,
- the scrape values are read from and written to the ConfigMap before Prometheus restarts.

`python -m pytest oxn/tests/unit` reports 171 passing tests and the 3 failures [change 18](18-formatting-and-type-fixes.md#known-limitations) lists.

## Known limitations

| Limitation | Status |
|---|---|
| Kubernetes is the only implementation, so the interface is only tested against it and against mocks. | Open |
| The action keys of interface-only treatments still contain `kubernetes` or `kube`, for example `kubernetes_loss`. | Open, renaming them breaks the specs |
| The SUE namespace and the names of the Prometheus and collector ConfigMaps are constants in `kubernetes_orchestrator.py`, not read from the spec. | Open |
| `set_otel_collector_probabilistic_sampling_values` takes `hash_seed` but does not write it, as in GOXN. | Open |
| `apply_security_context_to_deployment` returns an exit code and a message instead of raising, because `security_context_kubernetes` only logs them. | Open |
| `ready()` ignores its `timeout` and checks once that the required services exist. | Open, as in GOXN |
