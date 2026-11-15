"""Corrupt network packets of pods with tc netem"""

import logging
import time

from oxn.models.treatment import RuntimeTreatment
from oxn.models.treatment_params import NetworkParams, PercentString
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class PacketCorruptionParams(NetworkParams):
    """Params of kubernetes_corrupt, passed on to tc netem corrupt"""

    corrupt_percentage: PercentString
    corrupt_correlation: PercentString = "0%"


class KubernetesCorruptPacketTreatment(RuntimeTreatment[PacketCorruptionParams]):
    """Corrupt a percentage of the packets of a service"""

    action = "kubernetes_corrupt"
    Params = PacketCorruptionParams

    def preconditions(self) -> bool:
        super().preconditions()
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        try:
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment
            assert deployment.metadata is not None

            try:
                response = self.orchestrator.patch_deployment_to_include_steering_sidecar_container(
                    deployment=deployment
                )
                assert response

                if not response:
                    self.messages.append(
                        f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container"
                    )
                    return False
            except Exception as e:
                self.messages.append(
                    f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container: {e}"
                )
                return False
        except Exception as e:
            self.messages.append(
                f"Failed to patch the deployment with {label_selector}={label} in namespace {namespace} with steering sidecar container: {e}"
            )
            return False
        return True

    def inject(self) -> None:
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        duration = self.params.duration_seconds

        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

        assert deployment

        result = self.orchestrator.set_network_corruption(
            deployment, self.params.interface, self.params.corrupt_percentage, self.params.corrupt_correlation
        )

        if not result:
            logger.error(f"Failed to inject packet corruption into pods in {namespace} with {label_selector}={label}.")
            return
        logger.info(
            f"Injected packet corruption into pods in {namespace} with {label_selector}={label}. Waiting for {duration}s."
        )
        time.sleep(duration)

    def clean(self) -> None:
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)
        assert deployment
        result = self.orchestrator.remove_network_corruption(deployment, self.params.interface)
        if not result:
            logger.error(f"Failed to remove packet corruption from pods in {namespace} with {label_selector}={label}.")
            return
        logger.info(f"Removed packet corruption from pods in {namespace} with {label_selector}={label}.")

    def _validate_orchestrator(self) -> bool:
        return self._orchestrator_is_one_of(["kubernetes"])
