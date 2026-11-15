"""
Purpose: Defines the base classes of treatment parameters.
Functionality: TreatmentParams is the base class of the params of every treatment. The mixins and annotated types
    check values that several treatments share, such as durations and the pods a treatment targets.
Connection: Each treatment module defines a params model on top of these and names it in Treatment.Params. The spec model validates the params
    section of every treatment with it while parsing, see oxn.treatments.registry.TreatmentRegistry.
"""

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from oxn.common.utils import time_string_format_regex, time_string_to_seconds, validate_time_string
from oxn.models.workload import WorkloadSelector


def _check_time_string(value: str) -> str:
    if not validate_time_string(value):
        raise ValueError(f"Expected numbers with units like 90s or 1m30s, each matching {time_string_format_regex}")
    return value


def _check_percent_string(value: str) -> str:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)%", value)
    if not match or float(match.group(1)) > 100:
        raise ValueError("Expected a percentage between 0% and 100%, like 10%")
    return value


PROMETHEUS_DURATION_REGEX = r"(\d+y)?(\d+w)?(\d+d)?(\d+h)?(\d+m)?(\d+s)?(\d+ms)?"
"""The duration format of the Prometheus configuration, see https://prometheus.io/docs/prometheus/latest/configuration/configuration/#duration"""


def _check_prometheus_duration(value: str) -> str:
    if value != "0" and not (value and re.fullmatch(PROMETHEUS_DURATION_REGEX, value)):
        raise ValueError("Expected a Prometheus duration like 15s or 1m30s")
    return value


# the patterns only go into the JSON schema for editors, the validators check the values
TimeString = Annotated[
    str,
    AfterValidator(_check_time_string),
    Field(json_schema_extra={"pattern": r"^(\d+(us|ms|s|m|h|d))+$", "examples": ["90s", "1m30s"]}),
]
"""A duration oxn parses itself, like 90s or 1m30s, see oxn.common.utils.time_string_to_seconds"""

PercentString = Annotated[
    str,
    AfterValidator(_check_percent_string),
    Field(json_schema_extra={"pattern": r"^\d+(\.\d+)?%$", "examples": ["10%"]}),
]
"""A percentage passed on to tc netem, like 10%"""

PrometheusDuration = Annotated[
    str,
    AfterValidator(_check_prometheus_duration),
    Field(json_schema_extra={"pattern": f"^(0|{PROMETHEUS_DURATION_REGEX})$", "examples": ["15s", "1m"]}),
]
"""A duration passed on to the Prometheus configuration"""


class TreatmentParams(BaseModel):
    """
    Base class of the params of a treatment

    Unknown keys are errors, so typos don't get silently ignored. Params are frozen, a treatment that needs derived
    values computes them in properties.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)


class UncheckedParams(TreatmentParams):
    """Params of a spec that was loaded without checking its treatments, as oxn deploy and oxn teardown do"""

    model_config = ConfigDict(extra="allow", frozen=True)


class DurationParams(TreatmentParams):
    """Params of a runtime treatment that stays in place for a time"""

    duration: TimeString
    """How long the treatment stays in place"""

    @property
    def duration_seconds(self) -> float:
        return time_string_to_seconds(self.duration)


class PodSelectorParams(TreatmentParams):
    """Params that select the workload a treatment targets, on Kubernetes a deployment and its pods"""

    namespace: str
    label_selector: str
    """The label key, for example app.kubernetes.io/name"""
    label: str
    """The value of the label, for example recommendation"""

    @property
    def workload(self) -> WorkloadSelector:
        """The selected workload, as the orchestrator takes it"""
        return WorkloadSelector(namespace=self.namespace, label_selector=self.label_selector, label=self.label)


class NetworkParams(PodSelectorParams, DurationParams):
    """Params of a tc netem treatment"""

    interface: str
    """The network interface inside the pods, usually eth0"""
