"""Patch the security context of a deployment"""

import logging
from typing import List

from pydantic import Field

from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PodSelectorParams, TreatmentParams
from oxn.treatments.kubernetes import KubernetesTreatment

logger = logging.getLogger(__name__)


class Capabilities(TreatmentParams):
    """Linux capabilities of a Kubernetes security context"""

    add: List[str] = Field(min_length=1)
    drop: List[str] = Field(default_factory=list)


class SecurityContextParams(PodSelectorParams):
    """Params of security_context_kubernetes"""

    capabilities: Capabilities
    """Applied to every container of the deployment"""


class KubernetesApplySecurityContextTreatment(
    KubernetesTreatment[SecurityContextParams], CompileTimeTreatment[SecurityContextParams]
):
    """
    Treatment to escalate the privileges of a service account in a Kubernetes cluster

    Kubernetes only, it patches the security context in the pod template of a deployment.
    """

    action = "security_context_kubernetes"
    Params = SecurityContextParams

    def clean(self) -> None:
        return
        super().clean()
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label

        # capabilities should now be the opisite of what was applied in inject (e.g. inject was { add: ["NET_ADMIN"] } so clean should be { remove: ["NET_ADMIN"] })
        capabilities = {"add": []}

        error_code, error = self.kubernetes.apply_security_context_to_deployment(
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
        error_code, error = self.kubernetes.apply_security_context_to_deployment(
            namespace=namespace, label_selector=label_selector, label=label, capabilities=capabilities
        )
        logger.info(
            f"Applied security context to deployment in {namespace} with {label_selector}={label} with result {error_code}: {error}"
        )
        # TODO: check if the deployment was actually updated and if so, wait for the deployment to be ready

    def preconditions(self) -> bool:
        return True
