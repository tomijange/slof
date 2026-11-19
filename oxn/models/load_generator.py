import logging
from abc import ABC, abstractmethod

from oxn.models.experiment_spec import ExperimentSpec
from oxn.models.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class BaseLoadGenerator(ABC):
    """Abstract base class for load generators"""

    def __init__(self, orchestrator: Orchestrator, config: ExperimentSpec):
        assert orchestrator is not None, "Orchestrator must not be None"
        self.orchestrator = orchestrator
        """A reference to the orchestrator instance"""
        assert config is not None, "Config must not be None"
        self.config = config
        """The experiment spec"""
        self.env = None

    @abstractmethod
    def start(self):
        """Start the load generation"""
        pass

    @abstractmethod
    def stop(self):
        """Stop the load generation"""
        pass

    @abstractmethod
    def kill(self):
        """Kill all associated processes"""
        pass
