"""Kill pods of a service"""

import logging

from oxn.common.errors import OrchestratorException
from oxn.models.treatment import RuntimeTreatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class KubernetesKillTreatment(RuntimeTreatment):
    """
    Kill a Kubernetes Pod.
    """

    action = "kubernetes_kill"

    def preconditions(self) -> bool:
        """Check if the kubernetes pod is running"""
        super().preconditions()
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        amount_to_kill = self.config.get("amount_to_kill")
        try:
            assert namespace
            assert label_selector
            assert label
            assert amount_to_kill
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            self.pods = KubernetesOrchestrator.get_pods(self.orchestrator, namespace, label_selector, label)
            if self.pods is None:
                self.messages.append(f"Pod with {label_selector}={label} not found in namespace {namespace}")
                return False

            if len(self.pods) < amount_to_kill:
                self.messages.append(
                    f"Amount to kill is higher than the amount of pods matching the label selector. Amount to kill: {amount_to_kill}, amount of pods found for label selector: {len(self.pods)}"
                )
                return False

            for pod in self.pods:
                assert pod.metadata is not None
                if pod.status and pod.status.phase != "Running":
                    self.messages.append(f"At least one Pod ({pod.metadata.name}) is not running ({pod.status.phase})")
                    return False

        except OrchestratorException as e:
            self.messages.append(e.message)
            return False

        return True

    def inject(self) -> None:
        assert self.pods
        assert self.orchestrator
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        if not self.pods:
            logger.error("No pods found to kill")
            return

        amount_to_kill = self.config.get("amount_to_kill")
        pods_to_kill = self.pods[:amount_to_kill]
        for pod in pods_to_kill:
            KubernetesOrchestrator.kill_pod(self.orchestrator, pod)

        # TODO: scale down deployment of the pods?

        logger.debug(f"Killed {amount_to_kill} pods.")

    def clean(self) -> None:
        # TODO: Wait untill als pods are running again?
        super().clean()

    def params(self) -> dict:
        return {
            "namespace": str,
            "label_selector": str,
            "label": str,
            "amount_to_kill": int,
        }

    def _validate_params(self) -> bool:
        for key, value in self.params().items():
            if key == "namespace" and key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied for {self.treatment_type}")
            if key == "label_selector" and key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied for {self.treatment_type}")
            if key == "label" and key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied for {self.treatment_type}")
            if key == "amount_to_kill" and key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied for {self.treatment_type}")
        return not self.messages

    def _transform_params(self) -> None:
        return super()._transform_params()

    def _validate_orchestrator(self) -> bool:
        return self._orchestrator_is_one_of(["kubernetes"])
