"""
Purpose: Validates experiment specifications.
Functionality: Implements syntactic and semantic validation of experiment configurations.
Connection: Used by the Engine to ensure the experiment configuration is correct before execution.

Module to handle validation of experiment specifications"""
from typing import Set, List

import pydantic
import yaml

from oxn.models import orchestrator
from oxn.models.experiment_spec import (
    ExperimentSpec,
    MetricResponseDescription,
    TraceResponseDescription,
)

from oxn.common.errors import OxnException
from oxn.observability.jaeger import Jaeger
from oxn.observability.prometheus import Prometheus


class SemanticValidator:
    """Semantic validation for experiment specifications"""

    def __init__(self, experiment_spec: ExperimentSpec):
        self.experiment_spec = experiment_spec
        """The experiment specification to validate"""
        self.prometheus = Prometheus()
        """API to Prometheus required for label values and metric names"""
        self.jaeger = Jaeger()
        """API to Jaeger to required for service names"""
        self.metric_names = None
        """A set of metric names from Prometheus"""
        self.label_names = None
        """A set of label names from Prometheus"""
        self.label_values = None
        """A set of label values from Prometheus"""
        self.service_names = None
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
        return (
                self._validate_label_name(label=label)
                and label_value in self.label_values[label]
        )

    def _validate_labels(self, labels: dict):
        """Validate the labels dict from a metric response variable"""
        for k, v in labels.items():
            if not self._validate_label_name(k):
                self.messages.append(f"Prometheus does not recognize label name {k}")
            if not self._validate_label_value(k, v):
                self.messages.append(f"Prometheus does not recognize label value {v} for label {k}")

    def validate_metric_response_description(self, response: MetricResponseDescription) -> None:
        """Validate a single metric response variable description"""
        self._validate_metric_name(response.metric_name),
        self._validate_labels(response.labels),

    def validate_trace_response_description(self, response: TraceResponseDescription):
        """Validate a single trace response description from an experiment specification"""
        if response.service_name not in self.service_names:
            self.messages.append(f"Jaeger does not know service name {response.name}")

    def validate_treatment(self, treatment_description: dict):
        """
        Validate a single treatment description from an experiment specification
        """
        raise NotImplementedError

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

    def validate_treatments(self):
        for treatment in self.experiment_spec.experiment.treatments:
            self.validate_treatment(treatment_description=treatment)

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


def validate_syntax(experiment_spec: dict) -> ExperimentSpec:
    """Validate an experiment specification syntactically and return its typed model"""
    try:
        return ExperimentSpec.model_validate(experiment_spec)
    except pydantic.ValidationError as e:
        raise OxnException(
            message="Can't validate experiment spec", explanation=str(e)
        )


def load_experiment_specification(path: str) -> ExperimentSpec:
    """Read an experiment specification file and validate it syntactically"""
    return validate_syntax(read_experiment_specification(path))
