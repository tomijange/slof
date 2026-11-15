"""Change the OpenTelemetry metrics export interval of a service"""

import logging
import time

from oxn.common.utils import time_string_format_regex, time_string_to_seconds, to_milliseconds, validate_time_string
from oxn.models.treatment import CompileTimeTreatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class KubernetesMetricsExportIntervalTreatment(CompileTimeTreatment):
    """
    Modify the OTEL_METRICS_EXPORT interval for a given container

    check rate(otelcol_exporter_sent_metric_points[30s]) to validate the change

    config:
        namespace: system-under-evaluation,
        label_selector: app.kubernetes.io/component,
        label: recommendationservice,
        interval: 1s,
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_env_value = None
        self.env_name = "OTEL_METRIC_EXPORT_INTERVAL"
        
    def action(self):
        return "kubernetes_otel_metrics_interval"

    def preconditions(self) -> bool:
        super().preconditions()
        return True

    def inject(self) -> None:
        self.namespace = self.config.get("namespace")
        self.label_selector = self.config.get("label_selector")
        self.label = self.config.get("label")
        self.interval_ms = self.config.get("interval_ms")

        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        
        self.deployment = self.orchestrator.get_deployment(self.namespace, self.label_selector, self.label)
        
        deployment_environment_variables = self.orchestrator.get_deployment_env_parameters(
            deployment=self.deployment
        )
        
        # get self.env_name from the deployments environment variables
        for env_var in deployment_environment_variables:
            if env_var.name == self.env_name:
                self.init_env_value = env_var.value
                break 

        self.deployment = self.orchestrator.get_deployment(self.namespace, self.label_selector, self.label)
        result = self.orchestrator.set_deployment_env_parameter(
            deployment=self.deployment,
            environment_variable_name=self.env_name,
            environment_variable_value=str(int(self.interval_ms)),
        )
        
        logger.info(f"Environment variable '{self.env_name} set to '{self.interval_ms}'ms for the deployment '{self.deployment.metadata.name}'.")

        time.sleep(3)

        for x in range(0, 10):
            if self.orchestrator.is_deployment_ready(self.deployment):
                break
            logger.info(f"Waiting for deployment {self.deployment.metadata.name} to be ready")
            time.sleep(2)


    def clean(self) -> None:
        if self.init_env_value is None:
            return
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        # update the deployment as otherwise there will be an error because the deployment is outdated
        """ 
        TODO: uncomment this code before commit!
        self.deployment = self.orchestrator.get_deployment(self.namespace, self.label_selector, self.label)
        result = self.orchestrator.set_deployment_env_parameter(
            deployment=self.deployment,
            environment_variable_name=self.env_name,
            environment_variable_value=self.init_env_value,
        )
        logger.info(f"Environment variable '{self.env_name} reset for deployment '{self.deployment.metadata.name}' to initial value.") """

    def params(self) -> dict:
        return {
            "namespace": str,
            "label_selector": str,
            "label": str,
            "interval": str,
        }

    def _validate_params(self) -> bool:
        for key, value in self.params().items():
            if key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied")
            if not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key in self.config.items():
            if key == "interval" and not validate_time_string(self.config[key]):
                self.messages.append(
                    f"Value for parameter {key} has to match {time_string_format_regex} for {self.treatment_type}"
                )
        return not self.messages

    def _transform_params(self) -> None:
        """Convert the provided time string into milliseconds"""
        interval_s = time_string_to_seconds(self.config["interval"])
        interval_ms = to_milliseconds(interval_s)
        self.config["interval_ms"] = interval_ms

    def _validate_orchestrator(self) -> bool:
        return super()._validate_orchestrator(["kubernetes"])
