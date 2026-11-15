"""Scale a deployment to a number of replicas"""

import logging

from pydantic import Field

from oxn.common.errors import OrchestratorException
from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PodSelectorParams
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class DeploymentScaleParams(PodSelectorParams):
    """Params of scale_deployment"""

    scale_to: int = Field(ge=0)
    """The number of replicas while the treatment is in place"""


class DeploymentScaleTreatment(CompileTimeTreatment[DeploymentScaleParams]):
    """
    Will scale a deployment to scale_to replicas and back to the original number of replicas.
    """

    action = "scale_deployment"
    Params = DeploymentScaleParams

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.replicas_before = 0
        self.deployment = None

    def preconditions(self) -> bool:
        """Check if the deployment exists"""
        super().preconditions()
        return True

    def inject(self) -> None:
        super().inject()
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        scale_to = self.params.scale_to
        try:
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            self.deployment = KubernetesOrchestrator.get_deployment(self.orchestrator, namespace, label_selector, label)
            if self.deployment is None:
                self.messages.append(f"Deployment with {label_selector}={label} not found in namespace {namespace}")
                return
        except OrchestratorException as e:
            self.messages.append(str(e.message))
            return

        assert self.deployment.spec
        assert self.deployment.metadata
        assert self.deployment.metadata.name

        # Kubernetes runs one replica if the spec sets none
        self.replicas_before = self.deployment.spec.replicas if self.deployment.spec.replicas is not None else 1
        response = KubernetesOrchestrator.scale_deployment(self.orchestrator, self.deployment, scale_to)
        if response is None:
            self.messages.append(f"Failed to scale deployment {self.deployment.metadata.name} to {scale_to}")
            return
        # TODO: Wait until scaling is done
        logger.info(f"Deployment {self.deployment.metadata.name} scaled to {scale_to}")

    def clean(self) -> None:
        """
        Scale the deployment back to the original number of replicas.

        We have to fetch the deployment again as otherwise there will be an error form the kubernetes API because the deployment object is not up to date.
        """
        super().clean()
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        try:
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            self.deployment = KubernetesOrchestrator.get_deployment(self.orchestrator, namespace, label_selector, label)
            if self.deployment is None:
                self.messages.append(f"Deployment with {label_selector}={label} not found in namespace {namespace}")
                return
        except OrchestratorException as e:
            self.messages.append(str(e.message))
            return
        assert self.deployment.metadata
        assert self.deployment.metadata.name
        response = KubernetesOrchestrator.scale_deployment(self.orchestrator, self.deployment, self.replicas_before)
        if response is None:
            self.messages.append(
                f"Failed to scale deployment {self.deployment.metadata.name} to {self.replicas_before}"
            )
            return
        logger.info(f"Deployment {self.deployment.metadata.name} scaled to {self.replicas_before}")

    def _validate_orchestrator(self) -> bool:
        return self._orchestrator_is_one_of(["kubernetes"])
