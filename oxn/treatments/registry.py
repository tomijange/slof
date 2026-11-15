"""
Purpose: Knows every treatment oxn can run.
Functionality: Maps the action keys of the experiment specification to treatment classes, built-in ones and those
    loaded with --extend, and validates the params of a treatment with the params model of its class.
Connection: Passed to the spec validation, so treatment params are checked when the spec is loaded, before anything is
    deployed. The runner builds the treatments of a run from it.
"""

import inspect
import logging
from typing import Dict, Iterable, List

from oxn.common.errors import OxnException
from oxn.models.experiment_spec import TreatmentDescription
from oxn.models.orchestrator import Orchestrator
from oxn.models.treatment import Treatment
from oxn.models.treatment_params import TreatmentParams
from oxn.treatments.compile_time import (
    DeploymentScaleTreatment,
    KubernetesApplySecurityContextTreatment,
    MetricsExportIntervalTreatment,
    ProbabilisticHeadSamplingTreatment,
    PrometheusIntervalTreatment,
)
from oxn.treatments.runtime import (
    EmptyKubernetesTreatment,
    EmptyTreatment,
    KillTreatment,
    NetworkDelayTreatment,
    PacketCorruptionTreatment,
    PacketLossTreatment,
)

logger = logging.getLogger(__name__)

BUILTIN_TREATMENTS: List[type[Treatment]] = [
    EmptyTreatment,
    EmptyKubernetesTreatment,
    NetworkDelayTreatment,
    PacketLossTreatment,
    PacketCorruptionTreatment,
    KillTreatment,
    PrometheusIntervalTreatment,
    ProbabilisticHeadSamplingTreatment,
    MetricsExportIntervalTreatment,
    DeploymentScaleTreatment,
    KubernetesApplySecurityContextTreatment,
]
"""The treatments every registry starts with"""


class TreatmentRegistry:
    """
    The treatments an experiment can use, by action

    Implements oxn.models.experiment_spec.TreatmentCatalog, so passing it to the spec validation checks the action and
    params of every treatment while the spec is parsed.
    """

    def __init__(self, extensions: Iterable[type[Treatment]] = ()):
        self._classes: Dict[str, type[Treatment]] = {}
        for treatment_class in BUILTIN_TREATMENTS:
            self.register(treatment_class)
        for treatment_class in extensions:
            self.register(treatment_class)

    def register(self, treatment_class: type[Treatment]) -> None:
        """Make a treatment class available under its action, replacing a registered class with the same action"""
        action = getattr(treatment_class, "action", None)
        if not isinstance(action, str) or not action:
            raise OxnException(
                message=f"Treatment {treatment_class.__name__} has no action",
                explanation="Set the class attribute action to the key that selects it in experiment specifications",
            )
        params = getattr(treatment_class, "Params", None)
        if not (inspect.isclass(params) and issubclass(params, TreatmentParams)):
            raise OxnException(
                message=f"Treatment {treatment_class.__name__} has no params model",
                explanation="Set the class attribute Params to a subclass of oxn.models.treatment_params.TreatmentParams",
            )
        replaced = self._classes.get(action)
        if replaced is not None and replaced is not treatment_class:
            logger.info(f"Treatment {treatment_class.__name__} replaces {replaced.__name__} for action {action}")
        self._classes[action] = treatment_class

    @property
    def actions(self) -> List[str]:
        return list(self._classes)

    def treatment_class(self, action: str) -> type[Treatment]:
        treatment_class = self._classes.get(action)
        if treatment_class is None:
            raise OxnException(
                message=f"Unknown treatment action {action}",
                explanation=f"Known actions are {', '.join(sorted(self._classes))}",
            )
        return treatment_class

    def params_model(self, action: str) -> type[TreatmentParams]:
        return self.treatment_class(action).Params

    def build(self, description: TreatmentDescription, orchestrator: Orchestrator) -> Treatment:
        """Build the treatment a spec describes"""
        treatment_class = self.treatment_class(description.action)
        return treatment_class(params=description.params, name=description.name, orchestrator=orchestrator)
