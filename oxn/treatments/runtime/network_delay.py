"""Delay network traffic of a workload with tc netem"""

from oxn.models.treatment_params import NetworkParams, PercentString, TimeString
from oxn.treatments.runtime.netem import NetemTreatment


class DelayParams(NetworkParams):
    """Params of delay, passed on to tc netem delay"""

    delay_time: TimeString
    delay_jitter: TimeString = "0ms"
    delay_correlation: PercentString = "0%"


class NetworkDelayTreatment(NetemTreatment[DelayParams]):
    """Inject network delay into a service"""

    action = "delay"
    Params = DelayParams
    fault = "delay"

    def _apply(self) -> None:
        self.orchestrator.set_network_delay(
            self.params.workload,
            interface=self.params.interface,
            delay_time=self.params.delay_time,
            jitter=self.params.delay_jitter,
            correlation=self.params.delay_correlation,
        )
