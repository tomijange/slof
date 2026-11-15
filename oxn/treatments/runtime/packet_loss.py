"""Drop network packets of pods with tc netem"""

import logging
import time

from pydantic import Field

from oxn.common.log import log_exception
from oxn.models.treatment import RuntimeTreatment
from oxn.models.treatment_params import NetworkParams
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class PacketLossParams(NetworkParams):
    """Params of kubernetes_loss, passed on to tc netem loss"""

    loss_percentage: float = Field(ge=0, le=100)


class KubernetesNetworkPacketLossTreatment(RuntimeTreatment[PacketLossParams]):
    """
    Inject network errors into a service to induce packet loss

    To high values of loss_percentage can provoke a cascading effect and lead to nearly 100% packet loss
    To low values of loss_percentage can lead to no effect at all or a small increas in latency
    """

    action = "kubernetes_loss"
    Params = PacketLossParams

    def preconditions(self) -> bool:
        super().preconditions()
        """Check if the service has tc installed"""
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
        super().inject()
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        duration = self.params.duration_seconds

        assert isinstance(self.orchestrator, KubernetesOrchestrator)

        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

        assert deployment

        result = self.orchestrator.set_network_loss(
            deployment=deployment, interface=self.params.interface, loss=self.params.loss_percentage
        )

        if not result:
            logger.error(f"Failed to inject packet loss into pods in {namespace} with {label_selector}={label}.")
            return
        logger.info(
            f"Injected packet loss into pods in {namespace} with {label_selector}={label}. Waiting for {duration}s."
        )
        time.sleep(duration)

    def clean(self) -> None:
        super().clean()
        interface = self.params.interface
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        try:
            assert isinstance(self.orchestrator, KubernetesOrchestrator)

            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment

            result = self.orchestrator.remove_network_loss(deployment=deployment, interface=interface)

            if not result:
                logger.error(f"Failed to clean packet loss from pods in {namespace} with {label_selector}={label}.")
                return

            logger.info(f"Cleaned packet loss treatment from pods in {namespace} with {label_selector}={label}")
        except Exception as e:
            log_exception(
                logger, e, f"Cannot clean packet loss treatment from pods in {namespace} with {label_selector}={label}"
            )
            logger.error(f"State for pods in {namespace} with {label_selector}={label} might be polluted now")

    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True
