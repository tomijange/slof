"""Delay network traffic of pods with tc netem"""

import logging
import re
import time
from typing import Optional

from oxn.common.utils import time_string_format_regex, time_string_to_seconds, validate_time_string
from oxn.models.treatment import RuntimeTreatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class KubernetesNetworkDelayTreatment(RuntimeTreatment):
    """Inject network delay into a service"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = self.orchestrator

    action = "delay"

    def _validate_params(self) -> bool:
        for key, val in self.params().items():
            # required params
            if (
                    key in {"namespace", "label_selector", "label", "interface", "duration", "delay_time"}
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
            if key in {"duration", "delay_time", "delay_jitter"}:
                if not validate_time_string(value):
                    self.messages.append(
                        f"Value for parameter {key} has to match {time_string_format_regex} for {self.treatment_type}"
                    )
            if key == "delay_correlation":
                format_regex = r"\d+\%"
                if not bool(re.match(format_regex, value)):
                    self.messages.append(
                        f"Value for parameter {key} has to match {format_regex} for {self.treatment_type}"
                    )
            if key == "distribution":
                distribution_set = {"uniform", "pareto", "normal", "paretonormal"}
                if key not in distribution_set:
                    self.messages.append(
                        f"Value for parameter {key} has to be one of {distribution_set} for {self.treatment_type}"
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
            "delay_time": str,
            "delay_jitter": Optional[str],
            "delay_correlation": Optional[str],
            "delay_distribution": Optional[str],
        }

    def preconditions(self) -> bool:
        super().preconditions()
        """Check if the service has tc installed"""
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        assert namespace
        assert label_selector
        assert label

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
        
        return True

    def inject(self) -> None:
        super().inject()
        # required params
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        interface = self.config.get("interface")
        delay_time = self.config.get("delay_time")
        duration = self.config.get("duration_seconds")
        # optional params: use default values so we dont need to construct multiple commands
        jitter = self.config.get("delay_jitter", "0ms")
        correlation = self.config.get("delay_correlation", "0%")
        command = f"tc qdisc add dev {interface} root netem delay {delay_time} {jitter} {correlation}"
        try:
            assert namespace
            assert label_selector
            assert label
            assert duration
            assert isinstance(self.orchestrator, KubernetesOrchestrator)

            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment

            result = self.orchestrator.set_network_delay(deployment=deployment, interface=interface, delay_time=delay_time, jitter=jitter, correlation=correlation)
            
            if not result:
                logger.error(
                    f"Failed to inject delay into pods in {namespace} with {label_selector}={label}."
                )
                return
            logger.info(
                f"Injected delay into pods in {namespace} with {label_selector}={label}. Waiting for {duration}s."
            )
            time.sleep(duration)
        except Exception as e:
            logger.error(
                f"Failed to inject delay into pods in {namespace} with {label_selector}={label}: {e}"
            )

    def clean(self) -> None:
        super().clean()
        interface = self.config.get("interface") or "eth0"
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        assert namespace
        assert label_selector
        assert label
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

        assert deployment

        result = self.orchestrator.remove_network_delay(deployment=deployment, interface=interface)
        
        logger.info(f"Cleaned delay treatment from pods in {namespace} with {label_selector}={label}")
        #self.client.close()
            
    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True
