"""
Purpose: Validates experiment specifications.
Functionality: Implements syntactic and semantic validation of experiment configurations.
Connection: Used by the Engine to ensure the experiment configuration is correct before execution.

Module to handle validation of experiment specifications"""

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Set

import pydantic
import yaml

from oxn.common.errors import OxnException
from oxn.core.matrix import MatrixError, Variant, expand
from oxn.models.experiment_spec import (
    TREATMENTS_CONTEXT_KEY,
    ExperimentSpec,
    MetricResponseDescription,
    TraceResponseDescription,
)
from oxn.models.orchestrator import Orchestrator
from oxn.observability.jaeger import Jaeger
from oxn.observability.prometheus import Prometheus
from oxn.treatments.registry import TreatmentRegistry


class SemanticValidator:
    """Semantic validation for experiment specifications"""

    def __init__(self, experiment_spec: ExperimentSpec, orchestrator: Orchestrator):
        self.experiment_spec = experiment_spec
        """The experiment specification to validate"""
        self.prometheus = Prometheus(orchestrator=orchestrator)
        """API to Prometheus required for label values and metric names"""
        self.jaeger = Jaeger(orchestrator=orchestrator)
        """API to Jaeger to required for service names"""
        self.metric_names: Set[str] = set()
        """A set of metric names from Prometheus"""
        self.label_names: Set[str] = set()
        """A set of label names from Prometheus"""
        self.label_values: Dict[str, Set[str]] = {}
        """A set of label values from Prometheus"""
        self.service_names: Set[str] = set()
        """A set of service names from Jaeger"""
        self.metric_rvar_type = "metric"
        """Constant to represent the metric rvar type"""
        self.trace_rvar_type = "trace"
        """Constant to represent the trace rvar type"""
        self.messages: List[str] = []
        """List of messages to pass to CLI in case of failing validation"""
        self._populate_metrics()
        """Populate the metric name set"""
        self._populate_labels()
        """Populate the label name set"""
        self._populate_label_values()
        """Populate the label value set"""
        self._populate_service_names()
        """Populate the service name set """

    def _populate_service_names(self) -> Set[str]:
        """Call jaeger to get a list of service names from Jaeger traces"""
        service_names = self.jaeger.get_services()
        self.service_names = set(service_names)
        return self.service_names

    def _populate_metrics(self) -> Set[str]:
        """Call Prometheus to get a list of existing metric names"""
        prometheus_response = self.prometheus.metrics()
        metric_names = prometheus_response["data"]
        self.metric_names = set(metric_names)
        return self.metric_names

    def _populate_labels(self) -> Set[str]:
        """Call Prometheus to get all labels it knows about"""
        prometheus_response = self.prometheus.labels()
        label_names = prometheus_response["data"]
        self.label_names = set(label_names)
        return self.label_names

    def _populate_label_values(self) -> dict[str, Set[str]]:
        """For a given label, get all legal label values"""
        self.label_values = {}
        for label in self.label_names:
            prometheus_response = self.prometheus.label_values(label=label)
            label_values = prometheus_response["data"]
            self.label_values[label] = set(label_values)
        return self.label_values

    def _validate_metric_name(self, name: str) -> None:
        """A metric name is valid if it is recognized by Prometheus"""
        if name not in self.metric_names:
            self.messages.append(f"Prometheus does not recognize metric name {name}")

    def _validate_label_name(self, label: str) -> bool:
        """A label name is valid if it is recognized by Prometheus"""
        return label in self.label_names

    def _validate_label_value(self, label: str, label_value: str) -> bool:
        """A label value is valid if it is recognized by Prometheus given a valid label name"""
        return self._validate_label_name(label=label) and label_value in self.label_values[label]

    def _validate_labels(self, labels: dict):
        """Validate the labels dict from a metric response variable"""
        for k, v in labels.items():
            if not self._validate_label_name(k):
                self.messages.append(f"Prometheus does not recognize label name {k}")
            if not self._validate_label_value(k, v):
                self.messages.append(f"Prometheus does not recognize label value {v} for label {k}")

    def validate_metric_response_description(self, response: MetricResponseDescription) -> None:
        """Validate a single metric response variable description"""
        (self._validate_metric_name(response.metric_name),)
        (self._validate_labels(response.labels),)

    def validate_trace_response_description(self, response: TraceResponseDescription):
        """Validate a single trace response description from an experiment specification"""
        if response.service_name not in self.service_names:
            self.messages.append(f"Jaeger does not know service name {response.name}")

    def validate_response(self, response: MetricResponseDescription | TraceResponseDescription):
        """Validate a response variable"""
        # trace/metric is already validated by the spec model
        if response.type == "metric":
            self.validate_metric_response_description(response=response)
        if response.type == "trace":
            self.validate_trace_response_description(response=response)

    def validate_responses(self):
        """Validate the response section in the specification"""
        for response in self.experiment_spec.experiment.responses:
            self.validate_response(response=response)

    def validate(self):
        """Validate the experiment specification"""
        self.validate_responses()

        if self.messages:
            # something did not validate
            message = "\n".join(self.messages)
            raise OxnException(
                message="Experiment specification did not pass semantic validation",
                explanation=message,
            )


def read_experiment_specification(path: str) -> dict:
    """Read an experiment specification file and confirm that its valid yaml"""
    with open(path, "r") as fp:
        contents = fp.read()
        try:
            return yaml.safe_load(contents)
        except yaml.YAMLError as e:
            raise OxnException(
                message="Provided experiment spec is not valid YAML",
                explanation=str(e),
            )


def validate_syntax(
    experiment_spec: dict, treatments: TreatmentRegistry | None = None, check_treatments: bool = True
) -> ExperimentSpec:
    """
    Validate an experiment specification syntactically and return its typed model

    The action and params of every treatment are checked against treatments, the built-in treatments if it is None.
    With check_treatments=False they are not checked and the params stay UncheckedParams, for commands that only
    read other sections.
    """
    context = {}
    if check_treatments:
        context[TREATMENTS_CONTEXT_KEY] = treatments if treatments is not None else TreatmentRegistry()
    try:
        return ExperimentSpec.model_validate(experiment_spec, context=context)
    except pydantic.ValidationError as e:
        raise OxnException(message="Can't validate experiment spec", explanation=str(e))


@dataclass(frozen=True)
class ExperimentVariant:
    """One variant of an experiment spec and its typed model. A spec without a matrix has one, without levels."""

    variant: Variant
    spec: ExperimentSpec
    raw: Dict[str, Any]
    """The spec of the variant as read from YAML, with the placeholders filled in"""


def load_variants(
    path: str,
    treatments: TreatmentRegistry | None = None,
    check_treatments: bool = True,
    only: Sequence[str] = (),
) -> List[ExperimentVariant]:
    """
    Read an experiment specification file, expand its matrix and validate every selected variant syntactically

    only holds selections like sampling=10.0, see matrix.expand. Validation stops at the first invalid variant
    and names it. See validate_syntax for the other arguments.
    """
    raw = read_experiment_specification(path)
    if not isinstance(raw, dict):
        raise OxnException(message=f"Experiment spec {path} is not a mapping")
    try:
        rendered = expand(raw, only)
    except (MatrixError, pydantic.ValidationError) as e:
        raise OxnException(message=f"Can't expand the matrix of {path}", explanation=str(e))
    loaded = []
    for variant, raw in rendered:
        try:
            spec = validate_syntax(raw, treatments, check_treatments)
        except OxnException as e:
            if not variant.levels:
                raise
            raise OxnException(message=f"Can't validate variant {variant.id} of {path}", explanation=e.explanation)
        loaded.append(ExperimentVariant(variant=variant, spec=spec, raw=raw))
    return loaded


def load_experiment_specification(
    path: str, treatments: TreatmentRegistry | None = None, check_treatments: bool = True
) -> ExperimentSpec:
    """
    Read an experiment specification file and validate it syntactically, see validate_syntax

    For specs with a matrix of more than one variant use load_variants.
    """
    variants = load_variants(path, treatments, check_treatments)
    if len(variants) > 1:
        raise OxnException(
            message=f"{path} has a matrix with {len(variants)} variants",
            explanation="Select one variant, for example with --only " + variants[0].variant.id.split(",")[0],
        )
    return variants[0].spec
