"""
Purpose: Reads the fields of Kubernetes API objects that oxn needs.
Functionality: The models of the Kubernetes client declare nearly every field optional. These helpers return the
    fields as their required types and raise an OrchestratorException if an object lacks them, instead of an assert
    for every access.
Connection: Used by the KubernetesOrchestrator and the SteeringController.
"""

from typing import List, Tuple, Union

from kubernetes.client import V1ConfigMap, V1Container, V1Deployment, V1Pod, V1Service

from oxn.common.errors import OrchestratorException

KubernetesObject = Union[V1ConfigMap, V1Deployment, V1Pod, V1Service]


def name_and_namespace(obj: KubernetesObject) -> Tuple[str, str]:
    """Return the name and namespace from the metadata of an object"""
    metadata = obj.metadata
    if metadata is None or metadata.name is None or metadata.namespace is None:
        raise OrchestratorException(
            message=f"{type(obj).__name__} without name or namespace",
            explanation="Objects read from the Kubernetes API always have both",
        )
    return metadata.name, metadata.namespace


def pod_containers(deployment: V1Deployment) -> List[V1Container]:
    """Return the containers of the pod template of a deployment, which a patch of the deployment can change"""
    if deployment.spec is None or deployment.spec.template.spec is None:
        name, _ = name_and_namespace(deployment)
        raise OrchestratorException(
            message=f"Deployment {name} has no pod template",
            explanation="Deployments read from the Kubernetes API always have one",
        )
    return deployment.spec.template.spec.containers


def pod_selector(deployment: V1Deployment) -> str:
    """Return the label selector of the pods of a deployment, as list_namespaced_pod takes it"""
    labels = deployment.spec.selector.match_labels if deployment.spec else None
    if not labels:
        name, _ = name_and_namespace(deployment)
        # an empty selector would match every pod in the namespace
        raise OrchestratorException(
            message=f"Deployment {name} selects its pods without matchLabels",
            explanation="oxn only finds the pods of deployments that select them with matchLabels",
        )
    return ",".join(f"{key}={value}" for key, value in labels.items())
