"""
Purpose: Defines the base classes for treatments.
Functionality: Provides an abstract base class Treatment with methods to be implemented by subclasses,
and RuntimeTreatment and CompileTimeTreatment, which decide is_runtime() for them. Each treatment declares its
action key and the model of its params, see oxn/models/treatment_params.py.
Connection: Used as base classes for the treatment implementations in oxn/treatments/runtime and oxn/treatments/compile_time.
"""

import abc
import logging
import uuid
from typing import Any, ClassVar, Generic, List, Mapping, TypeVar, cast

import pydantic

from oxn.common.errors import OxnException
from oxn.common.utils import humanize_utc_timestamp
from oxn.models.orchestrator import Orchestrator
from oxn.models.treatment_params import TreatmentParams

logger = logging.getLogger(__name__)

P = TypeVar("P", bound=TreatmentParams)


class Treatment(abc.ABC, Generic[P]):
    """
    Base class of all treatments

    A subclass sets action, the key that selects it in the experiment specification, and Params, the model of its
    params section. The spec validates the params with that model while parsing, before anything is deployed, so a
    treatment instance always holds valid params.
    """

    action: ClassVar[str]
    """The key that selects this treatment in the action field of the experiment specification"""
    Params: ClassVar[type[TreatmentParams]] = TreatmentParams
    """The model of the params section, a subclass of TreatmentParams with the same type as P"""

    def __init__(self, params: P | Mapping[str, Any], name: str, orchestrator: Orchestrator):
        self.id: str = uuid.uuid4().hex
        """Random machine-readable unique identifier"""
        self.name: str = name
        """The name of the treatment as provided in the experiment specification"""
        self.orchestrator: Orchestrator = orchestrator
        """A reference to the orchestrator instance"""
        try:
            self.params: P = cast(P, self.validate_params(params))
            """The validated params from the experiment specification"""
        except pydantic.ValidationError as e:
            raise OxnException(message=f"Invalid params for treatment {name}", explanation=str(e))
        self.start: float | None = None
        """A unix float timestamp in utc indicating when the treatment instance has been started"""
        self.end: float | None = None
        """A unix float timestamp in utc indicating when the treatment instance has finished execution"""
        self.messages: List[str] = []
        """A list of strings to provide helpful messages to the user in case of any errors"""

        if not self._validate_orchestrator():
            raise OxnException(
                message=f"Invalid orchestrator for {self.__repr__()} provided.",
                explanation="\n".join(self.messages),
            )

    @classmethod
    def validate_params(cls, params: TreatmentParams | Mapping[str, Any]) -> TreatmentParams:
        """
        Return the params as an instance of Params

        Params from the spec are already validated and returned as they are. Mappings, for example from tests or
        extension code, and params of another model are validated here.

        :raises pydantic.ValidationError: if the params do not match Params
        """
        if isinstance(params, cls.Params):
            return params
        if isinstance(params, pydantic.BaseModel):
            params = params.model_dump()
        return cls.Params.model_validate(params)

    def __repr__(self):
        params = ", ".join(f"{key}={value}" for key, value in self.params.model_dump().items())
        return f"{self.__class__.__name__}(name={self.name}, {params})"

    @property
    def treatment_type(self):
        return self.__class__.__name__

    @property
    def short_id(self):
        """Return the truncated id for the treatment instance"""
        return self.id[:8]

    @property
    def humanize_start_time(self):
        """Provide a human-readable version of the start timestamp"""
        return humanize_utc_timestamp(self.start)

    @property
    def humanize_end_time(self):
        """Provide a human-readable version of the end timestamp"""
        return humanize_utc_timestamp(self.end)

    @abc.abstractmethod
    def preconditions(self) -> bool:
        """
        Return true if the preconditions for this treatment are met.

        Preconditions can be anything that is required for the treatment to successfully execute,
        such as third-party software. An implementation of this message should populate the messages
        instance variable to provide helpful error messages in case of unmet preconditions.
        Implementations for runtime treatments of this method can depend on a provisioned SUE,
        while implementations for compile time treatments cannot.

        :return: A boolean indicating if the preconditions for this treatment are met
        """
        logger.info(f"Checking preconditions for treatment {self.name}")
        return True

    @abc.abstractmethod
    def inject(self) -> None:
        """
        Inject the treatment. This method takes no arguments, it reads its arguments from self.params.

        :return: None
        """
        logger.info(f"Injecting treatment {self.name}")

    @abc.abstractmethod
    def clean(self) -> None:
        """
        Clean any residual effects of the treatment injection.
        :return:
        """
        logger.info(f"Cleaning treatment {self.name}")

    @abc.abstractmethod
    def is_runtime(self) -> bool:
        """
        Return True if the treatment is a runtime treatment and False otherwise

        Runtime treatments are treatments that are executed when the system under test is
        built and running, while compile time treatments are executed before the system under test is built.
        Compile time treatments change properties about the system that require a restart of the system or a rebuilding
        of the systems containers. We decided on introducing this distinction as it avoids having to restart
        containers during the runtime of the experiment, which sometimes made implementation awkward and lead to
        unexpected artefacts in the experiment data.


        :return: bool
        """
        return True

    def _validate_orchestrator(self) -> bool:
        """
        Return true if the orchestrator is suitable for this treatment

        Treatments that only use the methods of oxn.models.orchestrator.Orchestrator work with every orchestrator,
        which is the default. A treatment that needs more overrides this and explains why in self.messages, see
        oxn.treatments.kubernetes.KubernetesTreatment.
        """
        return True


class RuntimeTreatment(Treatment[P], abc.ABC):
    """
    Base class for runtime treatments

    The runner injects them one after another while the load generator runs, see Treatment.is_runtime.
    """

    def is_runtime(self) -> bool:
        return True


class CompileTimeTreatment(Treatment[P], abc.ABC):
    """
    Base class for compile-time treatments

    The runner injects them after the SUE is deployed and before the load starts. They change the SUE's
    configuration, which restarts its pods, and are cleaned after the runtime treatments.
    """

    def is_runtime(self) -> bool:
        return False
