"""Base class of the treatments that apply a tc netem fault to the instances of a workload"""

import abc
import logging
import time
from typing import TypeVar

from oxn.common.log import log_exception
from oxn.models.treatment import RuntimeTreatment
from oxn.models.treatment_params import NetworkParams

logger = logging.getLogger(__name__)

N = TypeVar("N", bound=NetworkParams)


class NetemTreatment(RuntimeTreatment[N], abc.ABC):
    """
    Apply a network fault for params.duration and remove it afterwards

    The orchestrator prepares the workload in preconditions(), on Kubernetes by adding the steering sidecar.
    Subclasses implement _apply() and name the fault in fault.
    """

    fault: str = "network fault"
    """What the treatment applies, for log messages"""

    @abc.abstractmethod
    def _apply(self) -> None:
        """Apply the fault with one of the network fault methods of the orchestrator"""

    def preconditions(self) -> bool:
        super().preconditions()
        workload = self.params.workload
        try:
            self.orchestrator.prepare_network_faults(workload)
        except Exception as e:
            self.messages.append(f"Failed to prepare the workload with {workload} for network faults: {e}")
            return False
        return True

    def inject(self) -> None:
        super().inject()
        workload = self.params.workload
        duration = self.params.duration_seconds
        try:
            self._apply()
        except Exception as e:
            log_exception(logger, e, f"Failed to inject {self.fault} into the workload with {workload}")
            return
        logger.info(f"Injected {self.fault} into the workload with {workload}. Waiting for {duration}s.")
        time.sleep(duration)

    def clean(self) -> None:
        super().clean()
        workload = self.params.workload
        try:
            self.orchestrator.remove_network_faults(workload, self.params.interface)
        except Exception as e:
            log_exception(logger, e, f"Cannot remove {self.fault} from the workload with {workload}")
            logger.error(f"State of the workload with {workload} might be polluted now")
            return
        logger.info(f"Removed {self.fault} from the workload with {workload}")
