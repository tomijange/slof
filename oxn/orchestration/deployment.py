"""
Purpose: Deploys and tears down the system under experiment (SUE) together with its surrounding observability stack.
Functionality: Takes the deployment section of an experiment spec (Helm releases and plain manifests), installs it
    step by step and removes it again in reverse order, leaving the cluster as it was before the experiment.
Connection: Used by the KubernetesOrchestrator to implement orchestrate() and teardown(), and by the oxn deploy and
    oxn teardown commands. The section itself is described by DeploymentDescription in models/experiment_spec.py.
"""
import logging
import shutil
import subprocess
import time
from typing import Callable, Dict, List, Optional, Union

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from oxn.common.errors import DeploymentException, OxnException
from oxn.models.experiment_spec import DeploymentDescription, ExperimentSpec, HelmRelease, Manifests

logger = logging.getLogger(__name__)

NAMESPACE_DELETION_TIMEOUT = 600
"""Seconds to wait for an owned namespace to disappear during teardown"""

CommandRunner = Callable[[List[str]], str]


def run_command(command: List[str]) -> str:
    """Run an external command (helm, kubectl) and return its stdout, raising DeploymentException on failure"""
    logger.info(f"$ {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.stdout.strip():
        logger.debug(result.stdout.strip())
    if result.returncode == 0 and result.stderr.strip():
        logger.debug(result.stderr.strip())
    if result.returncode != 0:
        raise DeploymentException(
            message=f"Command failed with exit code {result.returncode}: {' '.join(command)}",
            explanation=result.stderr.strip(),
        )
    return result.stdout


class Deployment:
    """
    Deployment of the SUE and its observability stack

    Steps are deployed in the order given and torn down in reverse order.
    """

    def __init__(self, description: DeploymentDescription, run: CommandRunner = run_command):
        self.namespaces = description.namespaces
        """Namespaces owned by the experiment"""
        self.steps = description.steps
        """The ordered deployment steps"""
        self._run = run
        self._core: Optional[client.CoreV1Api] = None

    @classmethod
    def from_experiment_spec(cls, experiment_spec: ExperimentSpec) -> Optional["Deployment"]:
        """Build the deployment of an experiment spec. Returns None if the spec has no deployment section."""
        description = experiment_spec.experiment.deployment
        if description is None:
            return None
        return cls(description)

    @property
    def core(self) -> client.CoreV1Api:
        if self._core is None:
            config.load_kube_config()
            self._core = client.CoreV1Api()
        return self._core

    def release(self, name: str) -> HelmRelease:
        """Look up a helm release step by name, e.g. to override its values before deploying"""
        for step in self.steps:
            if isinstance(step, HelmRelease) and step.release == name:
                return step
        raise OxnException(message=f"Deployment has no helm release named {name}")

    def deploy(self) -> None:
        """Deploy all steps in order. Re-deploying an existing deployment upgrades it in place."""
        _require_tools(self.steps)
        for namespace in self.namespaces:
            self._ensure_namespace(namespace.name, namespace.labels)
        for index, step in enumerate(self.steps, start=1):
            logger.info(f"Deploying {step} (step {index} of {len(self.steps)})")
            step_start = time.monotonic()
            if isinstance(step, HelmRelease):
                self._run(step.install_command())
            else:
                for command in step.apply_commands() + step.wait_commands():
                    self._run(command)
            logger.info(f"Deployed {step} in {time.monotonic() - step_start:.0f}s")
        logger.info("Deployment complete")

    def teardown(self) -> None:
        """Remove all steps in reverse order, then the owned namespaces"""
        _require_tools(self.steps)
        for step in reversed(self.steps):
            logger.info(f"Tearing down {step}")
            if isinstance(step, HelmRelease):
                self._uninstall(step)
            else:
                for command in step.delete_commands():
                    self._run(command)
        for namespace in reversed(self.namespaces):
            self._delete_namespace(namespace.name)
        logger.info("Teardown complete")

    def _uninstall(self, release: HelmRelease) -> None:
        try:
            self._run(release.status_command())
        except DeploymentException:
            logger.info(f"{release} is not installed, skipping")
            return
        self._run(release.uninstall_command())
        # helm keeps PVCs created from StatefulSet volumeClaimTemplates around, remove them explicitly
        logger.info(f"Deleting persistent volume claims of {release}")
        self.core.delete_collection_namespaced_persistent_volume_claim(
            namespace=release.namespace,
            label_selector=f"app.kubernetes.io/instance={release.release}",
        )

    def _ensure_namespace(self, name: str, labels: Dict[str, str]) -> None:
        try:
            self.core.read_namespace(name)
            logger.debug(f"Namespace {name} already exists")
            if labels:
                self.core.patch_namespace(name, {"metadata": {"labels": labels}})
        except ApiException as e:
            if e.status != 404:
                raise
            logger.info(f"Creating namespace {name}")
            self.core.create_namespace(
                client.V1Namespace(metadata=client.V1ObjectMeta(name=name, labels=labels or None))
            )

    def _delete_namespace(self, name: str) -> None:
        try:
            self.core.delete_namespace(name)
        except ApiException as e:
            if e.status == 404:
                return
            raise
        logger.info(f"Waiting for namespace {name} to be deleted")
        deadline = time.monotonic() + NAMESPACE_DELETION_TIMEOUT
        while time.monotonic() < deadline:
            try:
                self.core.read_namespace(name)
            except ApiException as e:
                if e.status == 404:
                    logger.info(f"Deleted namespace {name}")
                    return
                raise
            time.sleep(2)
        raise DeploymentException(
            message=f"Namespace {name} was not deleted within {NAMESPACE_DELETION_TIMEOUT}s",
            explanation="Check for resources with finalizers in the namespace",
        )


def _require_tools(steps: List[Union[HelmRelease, Manifests]]) -> None:
    tools = {"helm" if isinstance(step, HelmRelease) else "kubectl" for step in steps}
    missing = sorted(tool for tool in tools if shutil.which(tool) is None)
    if missing:
        raise DeploymentException(
            message=f"Missing required command line tools: {', '.join(missing)}",
            explanation="Install them and make sure they are on the PATH",
        )
