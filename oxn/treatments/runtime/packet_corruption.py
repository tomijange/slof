"""Corrupt network packets of pods with tc netem"""

import logging
import re
import time
from typing import Optional

from oxn.common.utils import time_string_format_regex, time_string_to_seconds, validate_time_string
from oxn.models.treatment import RuntimeTreatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class KubernetesCorruptPacketTreatment(RuntimeTreatment):
    def action(self):
        return "kubernetes_corrupt"

    def preconditions(self) -> bool:
        super().preconditions()
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
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        interface = self.config.get("interface")
        duration = self.config.get("duration_seconds")
        percentage = self.config.get("corrupt_percentage")
        correlation = self.config.get("corrupt_correlation") or "0%"

        assert duration
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)
       
        assert deployment
        
        result = self.orchestrator.orchestrate.set_network_corruption(deployment, interface, percentage, correlation)
        
        
        if not result:
            logger.error(
                f"Failed to inject packet loss into pods in {namespace} with {label_selector}={label}."
            )
            return
        logger.info(
            f"Injected packet loss into pods in {namespace} with {label_selector}={label}. Waiting for {duration}s."
        )
        time.sleep(duration)
        

        logger.info(
            f"Injected packet corruption into deployment {deployment.metadata.name}. Waiting for {duration}s."
        )
        time.sleep(duration)

    def clean(self) -> None:
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        interface = self.config.get("interface")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)
        assert deployment
        result = self.orchestrator.orchestrate.remove_network_corruption(deployment, interface)
        if not result:
            logger.error(
                f"Failed to remove packet loss from pods in {namespace} with {label_selector}={label}."
            )
            return
        logger.info(
            f"Removed packet loss from pods in {namespace} with {label_selector}={label}."
        )
        
    def params(self) -> dict:
        return {
            "namespace": str,
            "label_selector": str,
            "label": str,
            "interface": str,
            "duration": str,
            "corrupt_percentage": str,
            "corrupt_correlation": Optional[str],
        }
        
    def _validate_params(self) -> bool:
        bools = []
        for key, value in self.params().items():
            # required params
            if (
                    key in {"namespace", "label_selector", "label", "duration", "interface", "corrupt_percentage"}
                    and key not in self.config
            ):
                self.messages.append(f"Parameter {key} has to be supplied")
                bools.append(False)
            # supplied params have correct type
            if key in self.config and not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key, value in self.config.items():
            if key == "duration":
                if not validate_time_string(value):
                    self.messages.append(
                        f"Parameter {key} has to match {time_string_format_regex}"
                    )
                    bools.append(False)
            if key in {"corrupt_percentage", "corrupt_correlation"}:
                format_regex = r"^[1-9][0-9]?\%$|^100\%$"
                if not bool(re.match(format_regex, value)):
                    self.messages.append(f"Parameter {key} has to match {format_regex}")
                    bools.append(False)
        return all(bools)
    
    def _transform_params(self) -> None:
        relative_time_string = self.config.get("duration")
        relative_time_seconds = time_string_to_seconds(relative_time_string)
        self.config["duration_seconds"] = relative_time_seconds
        
    def _validate_orchestrator(self) -> bool:
        return super()._validate_orchestrator(["kubernetes"])
