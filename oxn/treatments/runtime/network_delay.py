"""Delay network traffic of pods with tc netem"""

import logging
import time

from oxn.models.treatment import RuntimeTreatment
from oxn.models.treatment_params import NetworkParams, PercentString, TimeString
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class DelayParams(NetworkParams):
    """Params of delay, passed on to tc netem delay"""

    delay_time: TimeString
    delay_jitter: TimeString = "0ms"
    delay_correlation: PercentString = "0%"


class KubernetesNetworkDelayTreatment(RuntimeTreatment[DelayParams]):
    """Inject network delay into a service"""

    action = "delay"
    Params = DelayParams

    def preconditions(self) -> bool:
        super().preconditions()
        """Check if the service has tc installed"""
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label

        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

        assert deployment
        assert deployment.metadata is not None

        try:
            response = self.orchestrator.patch_deployment_to_include_steering_sidecar_container(deployment=deployment)
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

        return True

    def inject(self) -> None:
        super().inject()
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        duration = self.params.duration_seconds
        try:
            assert isinstance(self.orchestrator, KubernetesOrchestrator)

            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment

            result = self.orchestrator.set_network_delay(
                deployment=deployment,
                interface=self.params.interface,
                delay_time=self.params.delay_time,
                jitter=self.params.delay_jitter,
                correlation=self.params.delay_correlation,
            )

            if not result:
                logger.error(f"Failed to inject delay into pods in {namespace} with {label_selector}={label}.")
                return
            logger.info(
                f"Injected delay into pods in {namespace} with {label_selector}={label}. Waiting for {duration}s."
            )
            time.sleep(duration)
        except Exception as e:
            logger.error(f"Failed to inject delay into pods in {namespace} with {label_selector}={label}: {e}")

    def clean(self) -> None:
        super().clean()
        interface = self.params.interface
        namespace = self.params.namespace
        label_selector = self.params.label_selector
        label = self.params.label
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

        assert deployment

        result = self.orchestrator.remove_network_delay(deployment=deployment, interface=interface)
        if not result:
            logger.error(f"Failed to clean delay treatment from pods in {namespace} with {label_selector}={label}.")
            return
        logger.info(f"Cleaned delay treatment from pods in {namespace} with {label_selector}={label}")

    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True
