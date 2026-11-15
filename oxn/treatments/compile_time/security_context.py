"""Patch the security context of a deployment"""

import logging
from typing import List

from pydantic import Field

from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PodSelectorParams, TreatmentParams
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class Capabilities(TreatmentParams):
    """Linux capabilities of a Kubernetes security context"""

    add: List[str] = Field(min_length=1)
    drop: List[str] = Field(default_factory=list)


class SecurityContextParams(PodSelectorParams):
    """Params of security_context_kubernetes"""

    capabilities: Capabilities
    """Applied to every container of the deployment"""


class KubernetesApplySecurityContextTreatment(CompileTimeTreatment[SecurityContextParams]):
    """
    Treatment to escalate the privileges of a service account in a Kubernetes cluster
    """

    action = "security_context_kubernetes"
    Params = SecurityContextParams

    def clean(self) -> None:
        return
        super().clean()
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        assert isinstance(self.orchestrator, KubernetesOrchestrator)

        # capabilities should now be the opisite of what was applied in inject (e.g. inject was { add: ["NET_ADMIN"] } so clean should be { remove: ["NET_ADMIN"] })
        capabilities = {"add": []}

        error_code, error = self.orchestrator.apply_security_context_to_deployment(
            namespace=namespace, label_selector=label_selector, label=label, capabilities=capabilities
        )

        logger.info(
            f"Applied security context to deployment in {namespace} with {label_selector}={label} with result {error_code}: {error}"
        )

    def inject(self) -> None:
        super().inject()
        capabilities = self.params.capabilities.model_dump()
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        error_code, error = self.orchestrator.apply_security_context_to_deployment(
            namespace=namespace, label_selector=label_selector, label=label, capabilities=capabilities
        )
        logger.info(
            f"Applied security context to deployment in {namespace} with {label_selector}={label} with result {error_code}: {error}"
        )
        # TODO: check if the deployment was actually updated and if so, wait for the deployment to be ready

    def preconditions(self) -> bool:
        return True

    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True
