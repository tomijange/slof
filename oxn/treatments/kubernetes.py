"""
Purpose: Base class of the treatments that only work on Kubernetes.
Functionality: KubernetesTreatment rejects other orchestrators when the treatment is built, and gives typed access to
    the KubernetesOrchestrator.
Connection: Used by treatments that change Kubernetes resources directly, such as security_context_kubernetes. All
    other treatments use the methods of oxn.models.orchestrator.Orchestrator and work with every orchestrator.
"""

import abc

from oxn.models.treatment import P, Treatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator


class KubernetesTreatment(Treatment[P], abc.ABC):
    """
    Base class of treatments that only work on Kubernetes

    Combine it with RuntimeTreatment or CompileTimeTreatment, with this class first:
    class MyTreatment(KubernetesTreatment[MyParams], CompileTimeTreatment[MyParams])
    """

    def _validate_orchestrator(self) -> bool:
        if isinstance(self.orchestrator, KubernetesOrchestrator):
            return True
        self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
        return False

    @property
    def kubernetes(self) -> KubernetesOrchestrator:
        """The orchestrator, which _validate_orchestrator checked to be a KubernetesOrchestrator"""
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        return self.orchestrator
