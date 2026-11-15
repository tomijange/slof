"""Drop network packets of pods with tc netem"""

import logging
import time

from oxn.common.log import log_exception
from oxn.common.utils import time_string_format_regex, time_string_to_seconds, validate_time_string
from oxn.models.treatment import RuntimeTreatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class KubernetesNetworkPacketLossTreatment(RuntimeTreatment):
    """
    Inject network errors into a service to induce packet loss
    
    To high values of loss_percentage can provoke a cascading effect and lead to nearly 100% packet loss
    To low values of loss_percentage can lead to no effect at all or a small increas in latency
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = self.orchestrator

    action = "kubernetes_loss"

    def _validate_params(self) -> bool:
        for key, val in self.params().items():
            # required params
            if (
                    key in {"namespace", "label_selector", "label", "interface", "duration", "loss_percentage"}
                    and key not in self.config
            ):
                self.messages.append(
                    f"Parameter {key} has to be supplied for {self.treatment_type}"
                )
            # supplied params have correct type
            if key in self.config and not isinstance(self.config[key], val):
                self.messages.append(
                    f"Parameter {key} has to be of type {val.__class__.__name__} for {self.treatment_type}"
                )
        for key, value in self.config.items():
            if key in {"duration"}:
                if not validate_time_string(value):
                    self.messages.append(
                        f"Value for parameter {key} has to match {time_string_format_regex} for {self.treatment_type}"
                    )
        return not self.messages

    def _transform_params(self) -> None:
        # correctly formatted params can be passed to tc directly as it can handle values + units
        # we need only transform the duration into seconds for the time.sleep call
        relative_time_string = self.config.get("duration")
        relative_time_seconds = time_string_to_seconds(relative_time_string)
        self.config["duration_seconds"] = relative_time_seconds

    def params(self) -> dict:
        return {
            "interface": str,
            "duration": str,
            "loss_percentage": float,
        }

    def preconditions(self) -> bool:
        super().preconditions()
        """Check if the service has tc installed"""
        #service = self.config.get("service_name")
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        try:
            assert namespace
            assert label_selector
            assert label
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment

            try:
                response = self.orchestrator.patch_deployment_to_include_steering_sidecar_container(deployment=deployment)
                assert response

                if not response:
                    self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container")
                    return False
            except Exception as e:
                self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container: {e}")
                return False
        except Exception as e:
            self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container: {e}")
            return False
        return True

    def inject(self) -> None:
        super().inject()
        # required params
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        interface = self.config.get("interface")
        duration = self.config.get("duration_seconds")
        loss_percentage = self.config.get("loss_percentage")
       
        assert namespace
        assert label_selector
        assert label
        assert duration
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

        assert deployment

        result = self.orchestrator.set_network_loss(deployment=deployment, interface=interface, loss=loss_percentage)
        
        if not result:
            logger.error(
                f"Failed to inject packet loss into pods in {namespace} with {label_selector}={label}."
            )
            return
        logger.info(
            f"Injected packet loss into pods in {namespace} with {label_selector}={label}. Waiting for {duration}s."
        )
        time.sleep(duration)

    def clean(self) -> None:
        super().clean()
        interface = self.config.get("interface") or "eth0"
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        try:
            assert namespace
            assert label_selector
            assert label
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            
            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment

            result = self.orchestrator.remove_network_loss(deployment=deployment, interface=interface)

            if not result:
                logger.error(f"Failed to clean packet loss from pods in {namespace} with {label_selector}={label}.")
                return
            
            logger.info(f"Cleaned packet loss treatment from pods in {namespace} with {label_selector}={label}")
            #self.client.close()
        except Exception as e:
            log_exception(logger, e, f"Cannot clean packet loss treatment from pods in {namespace} with {label_selector}={label}")
            logger.error(f"State for pods in {namespace} with {label_selector}={label} might be polluted now")
            
    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True
