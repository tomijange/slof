"""Patch the security context of a deployment"""

import logging

from oxn.common.utils import time_string_format_regex, validate_time_string
from oxn.models.treatment import CompileTimeTreatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class KubernetesApplySecurityContextTreatment(CompileTimeTreatment):
    """
    Treatment to escalate the privileges of a service account in a Kubernetes cluster
    """

    def clean(self) -> None:
        return
        super().clean()
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        
        assert namespace
        assert label_selector
        assert label
        assert self.config.get("capabilities")
        assert self.config.get("capabilities").get("add")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        
        # capabilities should now be the opisite of what was applied in inject (e.g. inject was { add: ["NET_ADMIN"] } so clean should be { remove: ["NET_ADMIN"] })
        capabilities = {"add": []}
        
        error_code, error = self.orchestrator.apply_security_context_to_deployment(
            namespace=namespace,
            label_selector=label_selector,
            label=label,
            capabilities=capabilities
        )
        
        logger.info(f"Applied security context to deployment in {namespace} with {label_selector}={label} with result {error_code}: {error}")

    def _transform_params(self) -> None:
        pass
    
    def _validate_params(self) -> bool:
        bools = []
        for key, value in self.params().items():
            if key in {"capabilities", "namespace", "label_selector", "label"} and key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied")
                bools.append(False)
            if key in self.config and not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key, value in self.config.items():
            if key == "duration":
                if not validate_time_string(value):
                    self.messages.append(
                        f"Parameter {key} has to match {time_string_format_regex}"
                    )
                    bools.append(False)
        return all(bools)

    def inject(self) -> None:
        super().inject()
        capabilities = self.config.get("capabilities")
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        
        assert namespace
        assert label_selector
        assert label
        assert capabilities and capabilities.get("add")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        error_code, error = self.orchestrator.apply_security_context_to_deployment(
            namespace=namespace,
            label_selector=label_selector,
            label=label,
            capabilities=capabilities
        )
        logger.info(f"Applied security context to deployment in {namespace} with {label_selector}={label} with result {error_code}: {error}")
        # TODO: check if the deployment was actually updated and if so, wait for the deployment to be ready

    def params(self) -> dict:
        return {
            "capabilities": dict,
            "namespace": str,
            "label_selector": str,
            "label": str,
        }

    def preconditions(self) -> bool:
        return True

    @property
    def action(self):
        return "security_context_kubernetes"

    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True
