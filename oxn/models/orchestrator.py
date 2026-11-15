"""
Purpose: Defines what oxn needs from an orchestrator.
Functionality: Orchestrator is the interface the engine, the load generators, the observability clients and the
    treatments use to deploy the SUE, reach its services and change it. Workloads are addressed with a
    WorkloadSelector, so nothing in the interface depends on Kubernetes.
Connection: Implemented by oxn.orchestration.kubernetes_orchestrator.KubernetesOrchestrator. Treatments that only work
    on Kubernetes subclass oxn.treatments.kubernetes.KubernetesTreatment instead of using Kubernetes types here.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from oxn.models.experiment_spec import ServiceReference
from oxn.models.workload import WorkloadInstance, WorkloadSelector


class Orchestrator(ABC):
    """
    Abstract base class for orchestrators

    Methods that change a workload raise an oxn.common.errors.OrchestratorException if they fail, and an
    OrchestratorResourceNotFoundException if the workload does not exist.
    """

    # Lifecycle of the SUE

    @abstractmethod
    def orchestrate(self):
        """Deploy the SUE, or do nothing if the spec expects it to be running already"""

    @abstractmethod
    def ready(self, expected_services: List[ServiceReference] | None = None, timeout: float = 120) -> bool:
        """Return true if the expected services, by default the required services of the spec, are running"""

    @abstractmethod
    def teardown(self):
        """Remove the SUE, or do nothing if orchestrate() did not deploy it"""

    # Addresses

    @abstractmethod
    def get_address_for_service(self, namespace: str, name: str) -> str:
        """Return the address of a service"""

    @abstractmethod
    def get_prometheus_address(self, target: str) -> str:
        """Return the address of the Prometheus of a target, sue or oxn"""

    @abstractmethod
    def get_jaeger_address(self) -> str:
        """Return the address of Jaeger"""

    # Workloads

    @abstractmethod
    def get_instances(self, workload: WorkloadSelector) -> List[WorkloadInstance]:
        """Return the running copies of a workload, at least one"""

    @abstractmethod
    def kill_instance(self, instance: WorkloadInstance) -> None:
        """Stop one copy of a workload immediately, without a grace period"""

    @abstractmethod
    def get_replicas(self, workload: WorkloadSelector) -> int:
        """Return how many copies of a workload should run"""

    @abstractmethod
    def scale(self, workload: WorkloadSelector, replicas: int) -> None:
        """Set how many copies of a workload should run"""

    @abstractmethod
    def restart(self, workload: WorkloadSelector) -> None:
        """Restart every copy of a workload and wait until it is ready again"""

    @abstractmethod
    def is_ready(self, workload: WorkloadSelector) -> bool:
        """Return true if every copy of a workload is ready"""

    @abstractmethod
    def get_environment_variable(self, workload: WorkloadSelector, name: str) -> Optional[str]:
        """Return the value of an environment variable of the main container of a workload, None if it is not set"""

    @abstractmethod
    def set_environment_variable(self, workload: WorkloadSelector, name: str, value: str) -> None:
        """Set an environment variable of the main container of a workload, which restarts its copies"""

    # Network faults with tc netem, inside every copy of a workload

    @abstractmethod
    def prepare_network_faults(self, workload: WorkloadSelector) -> None:
        """Make the copies of a workload able to take network faults, for example by adding a helper container"""

    @abstractmethod
    def set_network_delay(
        self, workload: WorkloadSelector, interface: str, delay_time: str, jitter: str, correlation: str
    ) -> None:
        """Delay the packets on an interface, see tc netem delay"""

    @abstractmethod
    def set_network_loss(self, workload: WorkloadSelector, interface: str, loss: float) -> None:
        """Drop a percentage of the packets on an interface, see tc netem loss random"""

    @abstractmethod
    def set_network_corruption(
        self, workload: WorkloadSelector, interface: str, percentage: str, correlation: str
    ) -> None:
        """Corrupt a percentage of the packets on an interface, see tc netem corrupt"""

    @abstractmethod
    def remove_network_faults(self, workload: WorkloadSelector, interface: str) -> None:
        """Remove the netem queueing discipline from an interface"""

    # Configuration of the SUE's telemetry components

    @abstractmethod
    def get_prometheus_scrape_values(self) -> Tuple[str, str, str]:
        """Return the global scrape interval, evaluation interval and scrape timeout of the SUE's Prometheus"""

    @abstractmethod
    def set_prometheus_scrape_values(self, scrape_interval: str, evaluation_interval: str, scrape_timeout: str) -> None:
        """Change the global scrape values of the SUE's Prometheus and restart it so they take effect"""

    @abstractmethod
    def get_otel_collector_probabilistic_sampling_values(self) -> Tuple[str, str]:
        """Return the sampling percentage and hash seed of the collector's probabilistic sampler"""

    @abstractmethod
    def set_otel_collector_probabilistic_sampling_values(self, sampling_percentage: float, hash_seed: int) -> None:
        """Change the collector's probabilistic sampler and restart the collector so it takes effect"""
