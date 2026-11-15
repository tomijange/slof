"""Change the OpenTelemetry metrics export interval of a service"""

import logging
import time
from typing import Optional

from oxn.common.utils import time_string_to_seconds, to_milliseconds
from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PodSelectorParams, TimeString

logger = logging.getLogger(__name__)


class MetricsExportIntervalParams(PodSelectorParams):
    """Params of kubernetes_otel_metrics_interval"""

    interval: TimeString
    """The new value of OTEL_METRIC_EXPORT_INTERVAL"""

    @property
    def interval_ms(self) -> float:
        return to_milliseconds(time_string_to_seconds(self.interval))


class MetricsExportIntervalTreatment(CompileTimeTreatment[MetricsExportIntervalParams]):
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
        self.init_env_value: Optional[str] = None
        self.env_name = "OTEL_METRIC_EXPORT_INTERVAL"

    def preconditions(self) -> bool:
        super().preconditions()
        return True

    def inject(self) -> None:
        workload = self.params.workload
        interval_ms = str(int(self.params.interval_ms))

        self.init_env_value = self.orchestrator.get_environment_variable(workload, self.env_name)
        try:
            self.orchestrator.set_environment_variable(workload, self.env_name, interval_ms)
        except Exception as e:
            logger.error(f"Failed to set {self.env_name} to {interval_ms}ms for the workload with {workload}: {e}")
            return

        logger.info(f"{self.env_name} set to {interval_ms}ms for the workload with {workload}")

        time.sleep(3)

        for _ in range(0, 10):
            if self.orchestrator.is_ready(workload):
                break
            logger.info(f"Waiting for the workload with {workload} to be ready")
            time.sleep(2)

    def clean(self) -> None:
        if self.init_env_value is None:
            return
        # TODO: reset the variable, which restarts the workload again:
        # self.orchestrator.set_environment_variable(self.params.workload, self.env_name, self.init_env_value)
