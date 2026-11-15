"""Kill instances of a workload"""

import logging
from typing import List

from pydantic import Field

from oxn.common.errors import OxnException
from oxn.models.treatment import RuntimeTreatment
from oxn.models.treatment_params import PodSelectorParams
from oxn.models.workload import WorkloadInstance

logger = logging.getLogger(__name__)


class KillParams(PodSelectorParams):
    """Params of kubernetes_kill"""

    amount_to_kill: int = Field(ge=1)
    """How many of the matching instances to kill"""


class KillTreatment(RuntimeTreatment[KillParams]):
    """
    Kill instances of a workload, pods on Kubernetes
    """

    action = "kubernetes_kill"
    Params = KillParams

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instances: List[WorkloadInstance] = []

    def preconditions(self) -> bool:
        """Check that enough instances of the workload are running"""
        super().preconditions()
        workload = self.params.workload
        amount_to_kill = self.params.amount_to_kill
        try:
            self.instances = self.orchestrator.get_instances(workload)
        except OxnException as e:
            self.messages.append(str(e.message))
            return False

        if len(self.instances) < amount_to_kill:
            self.messages.append(
                f"Amount to kill is higher than the amount of instances matching {workload}. Amount to kill: {amount_to_kill}, instances found: {len(self.instances)}"
            )
            return False

        for instance in self.instances:
            if not instance.running:
                self.messages.append(f"At least one instance ({instance.name}) is not running ({instance.state})")
                return False

        return True

    def inject(self) -> None:
        if not self.instances:
            logger.error("No instances found to kill")
            return

        amount_to_kill = self.params.amount_to_kill
        for instance in self.instances[:amount_to_kill]:
            self.orchestrator.kill_instance(instance)

        # TODO: scale down the workload of the instances?

        logger.debug(f"Killed {amount_to_kill} instances.")

    def clean(self) -> None:
        # TODO: Wait until all instances are running again?
        super().clean()
