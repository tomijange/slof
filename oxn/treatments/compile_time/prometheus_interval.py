"""Change the global scrape interval of Prometheus"""

import logging

from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PrometheusDuration, TreatmentParams
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class PrometheusIntervalParams(TreatmentParams):
    """Params of kubernetes_prometheus_interval, written to the global section of the Prometheus configuration"""

    interval: PrometheusDuration
    evaluation_interval: PrometheusDuration
    scrape_timeout: PrometheusDuration


class KubernetesPrometheusIntervalTreatment(CompileTimeTreatment[PrometheusIntervalParams]):
    """
    Treatment to change the global scrape interval of a Prometheus instance.

    """

    action = "kubernetes_prometheus_interval"
    Params = PrometheusIntervalParams

    def preconditions(self) -> bool:
        """Check that the config exists at the specified location and that Prometheus is running"""
        return True

    def inject(self) -> None:
        assert isinstance(self.orchestrator, KubernetesOrchestrator)

        self.deployment = self.orchestrator.get_deployment(
            "system-under-evaluation", "app.kubernetes.io/name", "prometheus"
        )

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

        self.orchestrator.restart_pods_of_deployment(self.deployment)

    def clean(self) -> None:
        return
        # if we clean up the changes to prometheus, the pods have to be restarted. The prometheus data is currently not persistent, so we would loose the benchmark data.

        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        self.orchestrator.set_prometheus_scrape_values(
            scrape_interval=self.initial_interval,
            evaluation_interval=self.initial_evaluation_interval,
            scrape_timeout=self.inital_scrape_timeout,
        )
        logger.info(
            f"Set prometheus scrape interval back to {self.initial_interval}, evaluation interval back to {self.initial_evaluation_interval} and scrape timeout back to {self.inital_scrape_timeout}"
        )

        self.deployment = self.orchestrator.get_deployment(
            "system-under-evaluation", "app.kubernetes.io/name", "prometheus"
        )
        self.orchestrator.restart_pods_of_deployment(self.deployment)

    def _validate_orchestrator(self) -> bool:
        return self._orchestrator_is_one_of(["kubernetes"])
