"""Change the OpenTelemetry metrics export interval of a service"""

import logging
import time

from oxn.common.utils import time_string_to_seconds, to_milliseconds
from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PodSelectorParams, TimeString
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class MetricsExportIntervalParams(PodSelectorParams):
    """Params of kubernetes_otel_metrics_interval"""

    interval: TimeString
    """The new value of OTEL_METRIC_EXPORT_INTERVAL"""

    @property
    def interval_ms(self) -> float:
        return to_milliseconds(time_string_to_seconds(self.interval))


class KubernetesMetricsExportIntervalTreatment(CompileTimeTreatment[MetricsExportIntervalParams]):
    """
    Modify the OTEL_METRICS_EXPORT interval for a given container

    check rate(otelcol_exporter_sent_metric_points[30s]) to validate the change

    params:
        namespace: system-under-evaluation,
        label_selector: app.kubernetes.io/component,
        label: recommendationservice,
        interval: 1s,
    """

    action = "kubernetes_otel_metrics_interval"
    Params = MetricsExportIntervalParams

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_env_value = None
        self.env_name = "OTEL_METRIC_EXPORT_INTERVAL"

    def preconditions(self) -> bool:
        super().preconditions()
        return True

    def inject(self) -> None:
        self.namespace = self.params.namespace
        self.label_selector = self.params.label_selector
        self.label = self.params.label
        self.interval_ms = self.params.interval_ms

        assert isinstance(self.orchestrator, KubernetesOrchestrator)

        self.deployment = self.orchestrator.get_deployment(self.namespace, self.label_selector, self.label)

        deployment_environment_variables = self.orchestrator.get_deployment_env_parameters(deployment=self.deployment)

        # get self.env_name from the deployments environment variables
        for env_var in deployment_environment_variables:
            if env_var.name == self.env_name:
                self.init_env_value = env_var.value
                break

        self.deployment = self.orchestrator.get_deployment(self.namespace, self.label_selector, self.label)
        assert self.deployment.metadata is not None
        result = self.orchestrator.set_deployment_env_parameter(
            deployment=self.deployment,
            environment_variable_name=self.env_name,
            environment_variable_value=str(int(self.interval_ms)),
        )
        if not result:
            logger.error(
                f"Failed to set environment variable '{self.env_name}' to '{self.interval_ms}'ms for the deployment '{self.deployment.metadata.name}'."
            )
            return

        logger.info(
            f"Environment variable '{self.env_name} set to '{self.interval_ms}'ms for the deployment '{self.deployment.metadata.name}'."
        )

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
        assert self.deployment.metadata is not None
        result = self.orchestrator.set_deployment_env_parameter(
            deployment=self.deployment,
            environment_variable_name=self.env_name,
            environment_variable_value=self.init_env_value,
        )
        logger.info(f"Environment variable '{self.env_name} reset for deployment '{self.deployment.metadata.name}' to initial value.") """

    def _validate_orchestrator(self) -> bool:
        return self._orchestrator_is_one_of(["kubernetes"])
