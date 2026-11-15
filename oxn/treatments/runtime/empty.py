"""Treatments that only observe the SUE"""

import time

from oxn.models.treatment import RuntimeTreatment
from oxn.models.treatment_params import DurationParams


class EmptyParams(DurationParams):
    """Params of empty and empty_kubernetes: only how long to wait"""


class EmptyTreatment(RuntimeTreatment[EmptyParams]):
    """
    Empty treatment to represent a simple observation of response variables
    """

    action = "empty"
    Params = EmptyParams

    def clean(self) -> None:
        pass

    def inject(self) -> None:
        time.sleep(self.params.duration_seconds)

    def preconditions(self) -> bool:
        return True

    def _validate_orchestrator(self) -> bool:
        return True


class EmptyKubernetesTreatment(EmptyTreatment):
    """
    Empty treatment to represent a simple observation of response variables, on Kubernetes only
    """

    action = "empty_kubernetes"

    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True
