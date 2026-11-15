"""Scale a workload to a number of replicas"""

import logging

from pydantic import Field

from oxn.common.errors import OxnException
from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import PodSelectorParams

logger = logging.getLogger(__name__)


class DeploymentScaleParams(PodSelectorParams):
    """Params of scale_deployment"""

    scale_to: int = Field(ge=0)
    """The number of replicas while the treatment is in place"""


class DeploymentScaleTreatment(CompileTimeTreatment[DeploymentScaleParams]):
    """
    Will scale a workload to scale_to replicas and back to the original number of replicas.
    """

    action = "scale_deployment"
    Params = DeploymentScaleParams

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.replicas_before = 0

    def preconditions(self) -> bool:
        """Check if the deployment exists"""
        super().preconditions()
        return True

    def inject(self) -> None:
        super().inject()
        workload = self.params.workload
        scale_to = self.params.scale_to
        try:
            self.replicas_before = self.orchestrator.get_replicas(workload)
            self.orchestrator.scale(workload, scale_to)
        except OxnException as e:
            self.messages.append(str(e.message))
            return
        # TODO: Wait until scaling is done
        logger.info(f"Workload with {workload} scaled to {scale_to}")

    def clean(self) -> None:
        """Scale the workload back to the original number of replicas"""
        super().clean()
        workload = self.params.workload
        try:
            self.orchestrator.scale(workload, self.replicas_before)
        except OxnException as e:
            self.messages.append(str(e.message))
            return
        logger.info(f"Workload with {workload} scaled to {self.replicas_before}")
