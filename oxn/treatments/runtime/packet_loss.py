"""Drop network packets of a workload with tc netem"""

from pydantic import Field

from oxn.models.treatment_params import NetworkParams
from oxn.treatments.runtime.netem import NetemTreatment


class PacketLossParams(NetworkParams):
    """Params of kubernetes_loss, passed on to tc netem loss"""

    loss_percentage: float = Field(ge=0, le=100)


class PacketLossTreatment(NetemTreatment[PacketLossParams]):
    """
    Inject network errors into a service to induce packet loss

    Too high values of loss_percentage can provoke a cascading effect and lead to nearly 100% packet loss.
    Too low values of loss_percentage can lead to no effect at all or a small increase in latency.
    """

    action = "kubernetes_loss"
    Params = PacketLossParams
    fault = "packet loss"

    def _apply(self) -> None:
        self.orchestrator.set_network_loss(
            self.params.workload, interface=self.params.interface, loss=self.params.loss_percentage
        )
