"""
Purpose: Defines the typed model of an experiment specification.
Functionality: Mirrors the structure of the experiment YAML files and validates them while parsing, so the rest of oxn
    works on attributes instead of nested dicts.
Connection: Built by validation.py and handed by the Engine to the orchestrators, load generators, runner and observer.
"""

import json
import os
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional, Protocol, Union

import pydantic
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializeAsAny,
    ValidationInfo,
    field_validator,
)

from oxn.models.treatment_params import TreatmentParams, UncheckedParams

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

    # the docstrings of fields become their descriptions in the JSON schema
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)


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
    grafana: Optional[ServiceReference] = None
    """The Grafana that --dashboard publishes the live dashboards to, with its dashboard and datasource sidecars"""


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


class TreatmentCatalog(Protocol):
    """
    What the spec needs to know about treatments to validate them, see oxn.treatments.registry.TreatmentRegistry

    Passed as the validation context key TREATMENTS_CONTEXT_KEY. Without it, actions are not checked and params stay
    UncheckedParams.
    """

    @property
    def actions(self) -> List[str]: ...

    def params_model(self, action: str) -> type[TreatmentParams]: ...


TREATMENTS_CONTEXT_KEY = "treatments"
"""Key of the TreatmentCatalog in the validation context of ExperimentSpec.model_validate"""


def _treatment_catalog(info: ValidationInfo) -> Optional[TreatmentCatalog]:
    return (info.context or {}).get(TREATMENTS_CONTEXT_KEY)


SPEC_DIR_CONTEXT_KEY = "spec_dir"
"""Key of the folder of the spec file in the validation context, which relative paths in the spec are resolved against"""


def _resolve_path(path: str, info: ValidationInfo) -> str:
    """A relative path joined with the folder of the spec file, if the context names it. Absolute paths stay as they are"""
    spec_dir = (info.context or {}).get(SPEC_DIR_CONTEXT_KEY)
    if spec_dir is None or os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(spec_dir, path))


def _describe_errors(error: pydantic.ValidationError) -> str:
    """Flatten the errors of a nested model, which pydantic only reports as one value error of the outer model"""
    return "; ".join(
        f"{'.'.join(str(part) for part in detail['loc']) or 'params'}: {detail['msg'].removeprefix('Value error, ')}"
        for detail in error.errors()
    )


class TreatmentDescription(SpecModel):
    """
    A treatment

    The action selects the treatment class, whose params model validates the params while the spec is parsed:

        treatments:
          - delay_treatment:
              action: delay
              params: {namespace: system-under-evaluation, label_selector: app.kubernetes.io/name,
                       label: recommendation, interface: eth0, duration: 10m, delay_time: 45ms}
    """

    name: str
    action: str
    params: SerializeAsAny[TreatmentParams] = Field(default_factory=UncheckedParams)
    """The params as the model of the treatment class, UncheckedParams if treatments are not checked"""

    @field_validator("action")
    @classmethod
    def _known_action(cls, action: str, info: ValidationInfo) -> str:
        catalog = _treatment_catalog(info)
        if catalog is not None and action not in catalog.actions:
            raise ValueError(f"Unknown action {action}, expected one of {', '.join(sorted(catalog.actions))}")
        return action

    @field_validator("params", mode="before")
    @classmethod
    def _params_of_action(cls, params: Any, info: ValidationInfo) -> Any:
        if isinstance(params, TreatmentParams):
            return params
        catalog = _treatment_catalog(info)
        action = info.data.get("action")
        # without a valid action, the action field already reports the error
        model = catalog.params_model(action) if catalog is not None and action is not None else UncheckedParams
        try:
            return model.model_validate(params)
        except pydantic.ValidationError as e:
            raise ValueError(_describe_errors(e))


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

    @field_validator("values")
    @classmethod
    def _values_next_to_the_spec(cls, values: List[str], info: ValidationInfo) -> List[str]:
        return [_resolve_path(path, info) for path in values]

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

    @field_validator("paths")
    @classmethod
    def _paths_next_to_the_spec(cls, paths: List[str], info: ValidationInfo) -> List[str]:
        return [_resolve_path(path, info) for path in paths]

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


def _has_pinned_tag(name: str) -> bool:
    """True if an image reference ends in a tag other than latest, or a digest"""
    last = name.rsplit("/", 1)[-1]
    if "@" in last:
        return True
    return ":" in last and last.rsplit(":", 1)[1] not in ("", "latest")


class ImageBuild(SpecModel):
    """
    A container image built with docker buildx and made available to the cluster, as one deployment step

    The step only builds and delivers the image. A treatment such as deployment_image, or the values of a Helm step,
    makes pods use it.
    """

    kind: Literal["image"] = "image"
    name: str
    """The image reference the pods use, with a tag other than latest, like ghcr.io/me/recommendation-rust:0.1.0"""
    context: str
    """The folder to build"""
    dockerfile: Optional[str] = None
    """The Dockerfile, by default the Dockerfile in context"""
    build_args: Dict[str, str] = Field(default_factory=dict)
    delivery: Literal["push", "import"] = "push"
    """push: push the image to the registry in name, the nodes pull it from there. import: import it into the
    containerd of every node through a short-lived privileged pod, without a registry"""
    platforms: List[str] = Field(default_factory=list)
    """For push, the platforms to build, like linux/amd64. By default, and always for import, the ones of the nodes"""

    @field_validator("context", "dockerfile")
    @classmethod
    def _paths_next_to_the_spec(cls, path: Optional[str], info: ValidationInfo) -> Optional[str]:
        return None if path is None else _resolve_path(path, info)

    @field_validator("name")
    @classmethod
    def _pinned(cls, name: str) -> str:
        # Kubernetes pulls latest images on every start, which fails for imported images and is not reproducible
        if not _has_pinned_tag(name):
            raise ValueError(f"Expected an image with a tag other than latest, like {name.split(':')[0]}:0.1.0")
        return name

    @field_validator("platforms")
    @classmethod
    def _platforms_only_for_push(cls, platforms: List[str], info: ValidationInfo) -> List[str]:
        if platforms and info.data.get("delivery") == "import":
            raise ValueError("An imported image is built for the platform of each node, leave out platforms")
        return platforms

    def build_command(self, platforms: List[str], output: str) -> List[str]:
        command = ["docker", "buildx", "build", "--platform", ",".join(platforms), "--tag", self.name]
        if self.dockerfile:
            command += ["--file", self.dockerfile]
        for key, value in self.build_args.items():
            command += ["--build-arg", f"{key}={value}"]
        return command + ["--output", output, self.context]

    def push_command(self, platforms: List[str]) -> List[str]:
        """Build for the platforms and push to the registry in name"""
        return self.build_command(platforms, "type=registry")

    def archive_command(self, platform: str, path: str) -> List[str]:
        """Build for one platform into an image archive at path, which ctr images import reads"""
        return self.build_command([platform], f"type=docker,dest={path}")

    def __str__(self):
        return f"image {self.name}"


DeploymentStep = Annotated[
    Union[HelmRelease, Manifests, ImageBuild],
    Field(discriminator="kind"),
    BeforeValidator(_flatten_entry("kind")),
]


class Namespace(SpecModel):
    """A namespace owned by the experiment, deleted on teardown"""

    name: str
    labels: Dict[str, str] = Field(default_factory=dict)


class DeploymentDescription(SpecModel):
    """
    The deployment section: Helm releases, plain manifests and images that make up the SUE and its observability stack

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
                values: [../deployments/values/values_opentelemetry_demo.yaml]
                set: {components.recommendation.resources.limits.cpu: 500m}
            - manifests:
                paths: [../k8s/elasticsearch/]
                namespace: system-under-evaluation
                wait_for: [deployment/elasticsearch]
            - image:
                name: slof.local/recommendation-rust:0.1.0
                context: images/recommendation-rust
                delivery: import

    Relative paths are resolved against the folder of the spec file, like the other paths in an experiment spec.
    """

    namespaces: List[Namespace] = Field(default_factory=list)
    steps: List[DeploymentStep]
    """The ordered deployment steps"""


class Sue(SpecModel):
    """The system under experiment as seen by the orchestrators"""

    exclude: List[str] = Field(default_factory=list)
    include: List[str] = Field(default_factory=list)
    required: List[ServiceReference] = Field(default_factory=list)
    """Kubernetes services that have to exist before the SUE counts as ready"""


class LocustFile(SpecModel):
    path: str

    @field_validator("path")
    @classmethod
    def _path_next_to_the_spec(cls, path: str, info: ValidationInfo) -> str:
        return _resolve_path(path, info)


class LoadgenTarget(ServiceReference):
    """The kubernetes service that receives the generated load"""

    port: int


class Loadgen(SpecModel):
    """The load generation section"""

    run_time: str
    max_users: int = 100
    spawn_rate: int = 10
    locust_files: List[LocustFile] = Field(default_factory=list)
    """The locust files that make up the load. With a target, all of them run, so their user classes need distinct
    names"""
    data_files: List[str] = Field(default_factory=list)
    """Files the locust files read, such as people.json. With a target, they are shipped next to the locust files"""
    target: Optional[LoadgenTarget] = None
    """If set, locust runs inside the cluster instead of in the oxn process"""
    namespace: str = "oxn-loadgen"
    """Where the in-cluster locust runs. Outside the SUE's namespace, so its CPU and energy do not count as the SUE's"""

    @field_validator("data_files")
    @classmethod
    def _data_files_next_to_the_spec(cls, paths: List[str], info: ValidationInfo) -> List[str]:
        return [_resolve_path(path, info) for path in paths]


class Experiment(SpecModel):
    """The experiment section, which is the only top level key of a spec"""

    version: str
    orchestrator: Literal["kubernetes"]
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
