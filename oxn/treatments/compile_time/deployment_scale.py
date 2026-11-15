"""Scale a deployment to a number of replicas"""

import logging

from oxn.common.errors import OrchestratorException
from oxn.models.treatment import CompileTimeTreatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class DeploymentScaleTreatment(CompileTimeTreatment):
    """
    Will scale a deployment to 0 replicas and back to the original number of replicas.
    """
    
    action = "scale_deployment"


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
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        scale_to = self.config.get("scale_to")
        assert scale_to is not None and scale_to >= 0 
        try:
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            self.deployment = KubernetesOrchestrator.get_deployment(self.orchestrator, namespace, label_selector, label)
            if self.deployment is None:
                self.messages.append(f"Deployment with {label_selector}={label} not found in namespace {namespace}")
                return
        except OrchestratorException as e:
            self.messages.append(e.message)
            return 
        
        assert self.deployment.spec
        assert self.deployment.metadata
        assert self.deployment.metadata.name

        self.replicas_before = self.deployment.spec.replicas
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
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        try:
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            self.deployment = KubernetesOrchestrator.get_deployment(self.orchestrator, namespace, label_selector, label)
            if self.deployment is None:
                self.messages.append(f"Deployment with {label_selector}={label} not found in namespace {namespace}")
                return
        except OrchestratorException as e:
            self.messages.append(e.message)
            return 
        assert self.deployment.metadata
        assert self.deployment.metadata.name
        response = KubernetesOrchestrator.scale_deployment(self.orchestrator, self.deployment, self.replicas_before)
        if response is None:
            self.messages.append(f"Failed to scale deployment {self.deployment.metadata.name} to {self.replicas_before}")
            return
        logger.info(f"Deployment {self.deployment.metadata.name} scaled to {self.replicas_before}")

    def params(self) -> dict:
        return {
            "namespace": str,
            "label_selector": str,
            "label": str,
            "scale_to": int,
        }

    def _validate_params(self) -> bool:
        """ 
        Check if all required parameters are supplied and have the correct type.        
        """

        for key, value in self.params().items():
            if key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied for {self.treatment_type}")
            if not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {value} for {self.treatment_type}")

        return not self.messages
        

    def _transform_params(self) -> None:
        pass

    def _validate_orchestrator(self) -> bool:
        return super()._validate_orchestrator(["kubernetes"])
