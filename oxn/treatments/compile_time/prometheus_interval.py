"""Change the global scrape interval of Prometheus"""

import logging

from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PrometheusDuration, TreatmentParams

logger = logging.getLogger(__name__)


class PrometheusIntervalParams(TreatmentParams):
    """Params of kubernetes_prometheus_interval, written to the global section of the Prometheus configuration"""

    interval: PrometheusDuration
    evaluation_interval: PrometheusDuration
    scrape_timeout: PrometheusDuration


class PrometheusIntervalTreatment(CompileTimeTreatment[PrometheusIntervalParams]):
    """
    Treatment to change the global scrape interval of a Prometheus instance.

    """

    action = "kubernetes_prometheus_interval"
    Params = PrometheusIntervalParams

    def preconditions(self) -> bool:
        """Check that the config exists at the specified location and that Prometheus is running"""
        return True

    def inject(self) -> None:
        self.initial_interval, self.initial_evaluation_interval, self.inital_scrape_timeout = (
            self.orchestrator.get_prometheus_scrape_values()
        )
        self.orchestrator.set_prometheus_scrape_values(
            scrape_interval=self.params.interval,
            evaluation_interval=self.params.evaluation_interval,
            scrape_timeout=self.params.scrape_timeout,
        )
        logger.info(
            f"Set prometheus scrape interval to {self.params.interval}, evaluation interval to {self.params.evaluation_interval} and scrape timeout to {self.params.scrape_timeout}"
        )

    def clean(self) -> None:
        # If we clean up the changes to prometheus, it has to be restarted. The prometheus data is currently not
        # persistent, so we would lose the benchmark data. To reset the values:
        # self.orchestrator.set_prometheus_scrape_values(
        #     scrape_interval=self.initial_interval,
        #     evaluation_interval=self.initial_evaluation_interval,
        #     scrape_timeout=self.inital_scrape_timeout,
        # )
        return
