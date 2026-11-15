"""Change the global scrape interval of Prometheus"""

import logging
import re

from oxn.models.treatment import CompileTimeTreatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class KubernetesPrometheusIntervalTreatment(CompileTimeTreatment):
    """
    Treatment to change the global scrape interval of a Prometheus instance.

    """

    def preconditions(self) -> bool:
        """Check that the config exists at the specified location and that Prometheus is running"""
        return True

    def inject(self) -> None:
        assert self.config.get("interval")
        assert self.config.get("evaluation_interval")
        assert self.config.get("scrape_timeout")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)

        self.deployment = self.orchestrator.get_deployment(
            "system-under-evaluation", "app.kubernetes.io/name", "prometheus"
        )

        self.initial_interval, self.initial_evaluation_interval, self.inital_scrape_timeout = (
            self.orchestrator.get_prometheus_scrape_values()
        )
        self.orchestrator.set_prometheus_scrape_values(
            scrape_interval=self.config.get("interval"),
            evaluation_interval=self.config.get("evaluation_interval"),
            scrape_timeout=self.config.get("scrape_timeout"),
        )
        logger.info(
            f"Set prometheus scrape interval to {self.config.get('interval')}, evaluation interval to {self.config.get('evaluation_interval')} and scrape timeout to {self.config.get('scrape_timeout')}"
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

    def params(self) -> dict:
        return {
            "interval": str,
            "evaluation_interval": str,
            "scrape_timeout": str,
        }

    def _validate_params(self) -> bool:
        for key, val in self.params().items():
            if key in self.config and not isinstance(self.config[key], val):
                self.messages.append(f"Parameter {key} has to be of type {val} for {self.treatment_type}")
        for key, value in self.config.items():
            prometheus_regex = (
                r"((([0-9]+)y)?(([0-9]+)w)?(([0-9]+)d)?(([0-9]+)h)?(([0-9]+)m)?((["
                r"0-9]+)s)?(([0-9]+)ms)?|0)"
            )
            if key == "interval" and not bool(re.match(prometheus_regex, value)):
                self.messages.append(f"Parameter {key} has to match {prometheus_regex} for {self.treatment_type}")
            if key == "evaluation_interval" and not bool(re.match(prometheus_regex, value)):
                self.messages.append(f"Parameter {key} has to match {prometheus_regex} for {self.treatment_type}")
            if key == "scrape_timeout" and not bool(re.match(prometheus_regex, value)):
                self.messages.append(f"Parameter {key} has to match {prometheus_regex} for {self.treatment_type}")
        return not self.messages

    def _transform_params(self) -> None:
        pass

    def _validate_orchestrator(self) -> bool:
        return self._orchestrator_is_one_of(["kubernetes"])

    @property
    def action(self):
        return "sampling"
