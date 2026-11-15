from abc import ABC, abstractmethod
from typing import List

from oxn.models.experiment_spec import ServiceReference


class Orchestrator(ABC):
    """
    Abstract base class for orchestrators.
    """

    @abstractmethod
    def orchestrate(self):
        pass

    @abstractmethod
    def ready(self, expected_services: List[ServiceReference] | None = None, timeout: float = 120) -> bool:
        pass

    @abstractmethod
    def teardown(self):
        pass

    @abstractmethod
    def translate_container_names(self, container_names: List[str]):
        pass

    # @abstractmethod
    # def execute_console_command(self, service: str, command: List[str]) -> Tuple[int, str]:
    #    """
    #    Execute a console command on the orchestrator

    #    Args:
    #        service: The service to execute the command on
    #        command: The command to execute

    #    Returns:
    #        A tuple of the return code and the output of the command

    #    """
    #    pass

    @abstractmethod
    def get_address_for_service(self, namespace: str, name: str) -> str:
        """
        Get the address for a service

        Args:
            namespace: The namespace of the service
            name: The name of the service

        Returns:
            The address of the service

        """
        pass

    @abstractmethod
    def get_prometheus_address(self, target: str) -> str:
        """
        Get the address for the Prometheus service of a target

        Returns:
            The address of the Prometheus service

        """
        pass

    @abstractmethod
    def get_jaeger_address(self) -> str:
        """
        Get the address for the Jaeger service

        Returns:
            The address of the Jaeger service

        """
        pass

    @abstractmethod
    def get_orchestrator_type(self) -> str:
        """
        Get the orchestrator type

        Returns:
            The orchestrator type

        """
        pass
