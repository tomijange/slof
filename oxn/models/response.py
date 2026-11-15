"""
Purpose: Defines the base class for response variables.
Functionality: Provides an abstract base class ResponseVariable with methods to be implemented by subclasses.
Connection: Used as a base class for specific response implementations in responses.py.

"""

import abc
import uuid

import pandas as pd


class ResponseVariable(abc.ABC):
    def __init__(
        self,
        experiment_start: float,
        experiment_end: float,
    ):
        self.id = uuid.uuid4().hex
        """Unique identifier"""
        self.experiment_start = experiment_start
        """UTC Timestamp of experiment start"""
        self.experiment_end = experiment_end
        """UTC Timestamp of experiment end"""
        self.name: str
        """Name of the response variable as defined in experiment specification, set by the subclass"""
        self.start: float
        """Start of the observation period, set by the subclass"""
        self.end: float
        """End of the observation period, set by the subclass"""
        self.data: pd.DataFrame | None = None
        """Observed data stored as a dataframe"""

    @property
    @abc.abstractmethod
    def short_id(self) -> str:
        pass

    @property
    def response_type(self) -> str:
        return self.__class__.__name__

    @abc.abstractmethod
    def label(
        self,
        treatment_start: float,
        treatment_end: float,
        label_column: str,
        label: str,
    ) -> None:
        pass

    @abc.abstractmethod
    def observe(self) -> pd.DataFrame:
        pass
