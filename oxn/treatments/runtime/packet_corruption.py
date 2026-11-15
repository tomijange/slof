"""Corrupt network packets of a workload with tc netem"""

from oxn.models.treatment_params import NetworkParams, PercentString
from oxn.treatments.runtime.netem import NetemTreatment


class PacketCorruptionParams(NetworkParams):
    """Params of kubernetes_corrupt, passed on to tc netem corrupt"""

    corrupt_percentage: PercentString
    corrupt_correlation: PercentString = "0%"


class PacketCorruptionTreatment(NetemTreatment[PacketCorruptionParams]):
    """Corrupt a percentage of the packets of a service"""

    action = "kubernetes_corrupt"
    Params = PacketCorruptionParams
    fault = "packet corruption"

    def _apply(self) -> None:
        self.orchestrator.set_network_corruption(
            self.params.workload,
            interface=self.params.interface,
            percentage=self.params.corrupt_percentage,
            correlation=self.params.corrupt_correlation,
        )
