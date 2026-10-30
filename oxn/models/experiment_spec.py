"""
Purpose: Defines the typed model of an experiment specification.
Functionality: Mirrors the structure of the experiment YAML files and validates them while parsing, so the rest of oxn
    works on attributes instead of nested dicts.
Connection: Built by validation.py and handed by the Engine to the orchestrators, load generators, runner and observer.
"""
import json
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

DEFAULT_TIMEOUT = "15m"
"""Default time to wait for a single deployment step"""


def _flatten_entry(key_field: str) -> Callable[[Any], Any]:
    """Build a validator that turns a `- key: {...}` list entry of the spec into `{key_field: key, ...}`"""

    def flatten(entry: Any) -> Any:
        if not isinstance(entry, dict):
            return entry
        if len(entry) != 1:
            raise ValueError(f"Expected a single key, got {list(entry)}")
        key, description = next(iter(entry.items()))
        if not isinstance(description, dict) or key_field in description:
            raise ValueError(f"Expected a mapping without the key {key_field} below {key}")
        return {key_field: key, **description}

    return flatten


class SpecModel(BaseModel):
    """Base class of all spec sections. Unknown keys are errors, so typos don't get silently ignored."""

    model_config = ConfigDict(extra="forbid")


class ServiceReference(SpecModel):
    """A kubernetes service"""

    name: str
    namespace: str


class PrometheusService(ServiceReference):
    """A Prometheus instance responses can read from"""

    target: str
    """The value of the target field of the metric responses that read from this instance"""


class Services(SpecModel):
    """The observability backends oxn reads responses from"""

    jaeger: ServiceReference
    prometheus: List[PrometheusService]


class MetricResponseDescription(SpecModel):
    """A response variable read from Prometheus"""

    name: str
    type: Literal["metric"]
    target: str
    metric_name: str
    step: int
    left_window: str
    right_window: str
    labels: Dict[str, str] = Field(default_factory=dict)


class TraceResponseDescription(SpecModel):
    """A response variable read from Jaeger"""

    name: str
    type: Literal["trace"]
    service_name: str
    left_window: str
    right_window: str
    limit: int = 100


ResponseDescription = Annotated[
    Union[MetricResponseDescription, TraceResponseDescription],
    Field(discriminator="type"),
    BeforeValidator(_flatten_entry("name")),
]


class TreatmentDescription(SpecModel):
    """A treatment, its params are validated by the treatment class matching the action"""

    name: str
    action: str
    params: Dict[str, Any]


class HelmRelease(SpecModel):
    """A helm chart installed as one deployment step"""

    kind: Literal["helm"] = "helm"
    release: str
    chart: str
    namespace: str
    repo: Optional[str] = None
    version: Optional[str] = None
    values: List[str] = Field(default_factory=list)
    set: Dict[str, Any] = Field(default_factory=dict)
    """Individual value overrides, applied after all values files"""
    timeout: str = DEFAULT_TIMEOUT

    def install_command(self) -> List[str]:
        command = ["helm", "upgrade", "--install", self.release, self.chart]
        if self.repo:
            command += ["--repo", self.repo]
        if self.version:
            command += ["--version", self.version]
        command += ["--namespace", self.namespace, "--create-namespace"]
        for path in self.values:
            command += ["--values", path]
        for key, value in self.set.items():
            command += ["--set-json", f"{key}={json.dumps(value)}"]
        command += ["--wait", "--timeout", self.timeout]
        return command

    def status_command(self) -> List[str]:
        return ["helm", "status", self.release, "--namespace", self.namespace]

    def uninstall_command(self) -> List[str]:
        return ["helm", "uninstall", self.release, "--namespace", self.namespace, "--wait", "--timeout", self.timeout]

    def __str__(self):
        return f"helm release {self.namespace}/{self.release}"


class Manifests(SpecModel):
    """Plain kubernetes manifests applied with kubectl as one deployment step"""

    kind: Literal["manifests"] = "manifests"
    paths: List[str]
    namespace: Optional[str] = None
    wait_for: List[str] = Field(default_factory=list)
    """Resources like deployment/elasticsearch whose rollout must finish before the next step starts"""
    timeout: str = DEFAULT_TIMEOUT

    def _namespace_args(self) -> List[str]:
        return ["--namespace", self.namespace] if self.namespace else []

    def apply_commands(self) -> List[List[str]]:
        return [["kubectl", "apply", *self._namespace_args(), "-f", path] for path in self.paths]

    def wait_commands(self) -> List[List[str]]:
        return [
            ["kubectl", "rollout", "status", *self._namespace_args(), resource, f"--timeout={self.timeout}"]
            for resource in self.wait_for
        ]

    def delete_commands(self) -> List[List[str]]:
        return [
            ["kubectl", "delete", *self._namespace_args(), "-f", path, "--ignore-not-found", "--wait"]
            for path in reversed(self.paths)
        ]

    def __str__(self):
        return f"manifests {', '.join(self.paths)}"


DeploymentStep = Annotated[
    Union[HelmRelease, Manifests],
    Field(discriminator="kind"),
    BeforeValidator(_flatten_entry("kind")),
]


class Namespace(SpecModel):
    """A namespace owned by the experiment, deleted on teardown"""

    name: str
    labels: Dict[str, str] = Field(default_factory=dict)


class DeploymentDescription(SpecModel):
    """
    The deployment section: Helm releases and plain manifests that make up the SUE and its observability stack

    The section looks like this (see experiments/ for complete examples):

        deployment:
          namespaces:
            - name: system-under-evaluation
              labels: {istio-injection: enabled}
          steps:
            - helm:
                release: astronomy-shop
                chart: opentelemetry-demo
                repo: https://open-telemetry.github.io/opentelemetry-helm-charts
                version: 0.42.6
                namespace: system-under-evaluation
                values: [deployments/values/values_opentelemetry_demo.yaml]
                set: {components.recommendation.resources.limits.cpu: 500m}
            - manifests:
                paths: [k8s/elasticsearch/]
                namespace: system-under-evaluation
                wait_for: [deployment/elasticsearch]

    Relative paths are resolved against the current working directory, like the other paths in an experiment spec.
    """

    namespaces: List[Namespace] = Field(default_factory=list)
    steps: List[DeploymentStep]
    """The ordered deployment steps"""


class Sue(SpecModel):
    """The system under experiment as seen by the orchestrators"""

    compose: str
    """Path of the docker compose file, not used on kubernetes"""
    exclude: List[str] = Field(default_factory=list)
    include: List[str] = Field(default_factory=list)
    required: List[ServiceReference] = Field(default_factory=list)
    """Kubernetes services that have to exist before the SUE counts as ready"""


class LocustFile(SpecModel):
    path: str


class LoadgenTarget(ServiceReference):
    """The kubernetes service that receives the generated load"""

    port: int


class Loadgen(SpecModel):
    """The load generation section"""

    run_time: str
    max_users: int = 100
    spawn_rate: int = 10
    locust_files: List[LocustFile] = Field(default_factory=list)
    target: Optional[LoadgenTarget] = None
    """If set, locust runs inside the cluster instead of in the oxn process"""


class Experiment(SpecModel):
    """The experiment section, which is the only top level key of a spec"""

    version: str
    orchestrator: Literal["docker-compose", "kubernetes"]
    services: Optional[Services] = None
    responses: List[ResponseDescription]
    treatments: List[Annotated[TreatmentDescription, BeforeValidator(_flatten_entry("name"))]] = Field(
        default_factory=list
    )
    deployment: Optional[DeploymentDescription] = None
    """Deployment of the SUE, None if the spec expects an already running SUE"""
    sue: Sue
    loadgen: Loadgen


class ExperimentSpec(SpecModel):
    """A complete experiment specification"""

    experiment: Experiment
