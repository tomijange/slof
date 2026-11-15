"""
Purpose: Names the parts of the SUE that treatments act on, independent of the orchestrator.
Functionality: WorkloadSelector selects a workload, WorkloadInstance is one running copy of it.
Connection: Treatments pass them to the methods of oxn.models.orchestrator.Orchestrator. PodSelectorParams in
    oxn/models/treatment_params.py builds a WorkloadSelector from the params of a treatment.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkloadSelector:
    """
    Selects a workload of the SUE by a label of its instances

    On Kubernetes a workload is a deployment and its instances are pods. In Docker Compose it would be a service and
    its containers, with the project as namespace and a container label such as com.docker.compose.service.
    """

    namespace: str
    label_selector: str
    """The label key, for example app.kubernetes.io/name"""
    label: str
    """The value of the label, for example recommendation"""

    def __str__(self) -> str:
        return f"{self.label_selector}={self.label} in namespace {self.namespace}"


@dataclass(frozen=True)
class WorkloadInstance:
    """One running copy of a workload, a pod on Kubernetes"""

    name: str
    namespace: str
    state: str
    """The state as the orchestrator reports it, for example the phase of a pod"""
    running: bool
