"""
Purpose: Deploys and tears down the system under experiment (SUE) together with its surrounding observability stack.
Functionality: Takes the deployment section of an experiment spec (Helm releases, plain manifests and images), installs
    it step by step and removes it again in reverse order, leaving the cluster as it was before the experiment.
Connection: Used by the KubernetesOrchestrator to implement orchestrate() and teardown(), and by the oxn deploy and
    oxn teardown commands. The section itself is described by DeploymentDescription in models/experiment_spec.py.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Callable, Dict, List, Optional, Sequence

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from oxn.common.errors import DeploymentException, OxnException
from oxn.models.experiment_spec import DeploymentDescription, DeploymentStep, ExperimentSpec, HelmRelease, ImageBuild

logger = logging.getLogger(__name__)

NAMESPACE_DELETION_TIMEOUT = 600
"""Seconds to wait for an owned namespace to disappear during teardown"""

IMPORT_NAMESPACE = "kube-system"
"""Namespace of the pods that import images into the containerd of a node, which allows privileged pods"""

IMPORT_HELPER_IMAGE = "docker.io/library/busybox:1.37.0"
"""Image of the import pods, it only needs sh and nsenter"""

IMPORT_SCRIPT = """
for socket in /var/snap/microk8s/common/run/containerd.sock /run/k3s/containerd/containerd.sock \\
        /run/containerd/containerd.sock; do
    [ -S "$socket" ] || continue
    case "$socket" in
        /var/snap/microk8s/*) ctr=/snap/microk8s/current/bin/ctr ;;
        /run/k3s/*) ctr="/usr/local/bin/k3s ctr" ;;
        *) ctr=ctr ;;
    esac
    exec $ctr --address "$socket" --namespace k8s.io images import -
done
echo "No containerd socket of MicroK8s, k3s or containerd found on the node" >&2
exit 1
"""
"""Imports the image archive on stdin into the containerd of the node, run in the mount namespace of the node"""

CommandRunner = Callable[..., str]
"""Runs a command, optionally with a file as stdin, see run_command"""


def run_command(command: List[str], input_path: Optional[str] = None) -> str:
    """
    Run an external command (helm, kubectl, docker) and return its stdout, raising DeploymentException on failure

    With input_path, the file is the stdin of the command.
    """
    logger.info(f"$ {' '.join(command)}" + (f" < {input_path}" if input_path else ""))
    if input_path is None:
        result = subprocess.run(command, capture_output=True, text=True)
    else:
        with open(input_path, "rb") as stdin:
            result = subprocess.run(command, stdin=stdin, capture_output=True, text=True)
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
            elif isinstance(step, ImageBuild):
                self._deliver_image(step)
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
            elif isinstance(step, ImageBuild):
                # an image is not part of the cluster's state that a run changes, the next run reuses it
                logger.info(f"Keeping {step}")
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

    def _deliver_image(self, image: ImageBuild) -> None:
        """Build an image and push it, or import it into every node, for the platforms of the nodes"""
        nodes_by_platform = self._nodes_by_platform()
        if image.delivery == "push":
            self._run(image.push_command(image.platforms or sorted(nodes_by_platform)))
            return
        with tempfile.TemporaryDirectory(prefix="oxn-image-") as folder:
            for platform, nodes in sorted(nodes_by_platform.items()):
                archive = os.path.join(folder, f"{platform.replace('/', '-')}.tar")
                self._run(image.archive_command(platform, archive))
                for node in nodes:
                    self._import_on_node(node, archive, image)

    def _nodes_by_platform(self) -> Dict[str, List[str]]:
        nodes: Dict[str, List[str]] = {}
        for node in self.core.list_node().items:
            name = node.metadata.name if node.metadata else None
            info = node.status.node_info if node.status else None
            if name is None or info is None:
                raise DeploymentException(
                    message=f"Node {name} reports no name or platform",
                    explanation="Its metadata has no name or its status no nodeInfo",
                )
            nodes.setdefault(f"{info.operating_system}/{info.architecture}", []).append(name)
        if not nodes:
            raise DeploymentException(message="The cluster has no nodes to build images for")
        return nodes

    def _import_on_node(self, node: str, archive: str, image: ImageBuild) -> None:
        """Stream an image archive into the containerd of a node, through a privileged pod in its PID namespace"""
        name = f"oxn-image-import-{uuid.uuid4().hex[:8]}"
        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=name, namespace=IMPORT_NAMESPACE, labels={"app.kubernetes.io/managed-by": "oxn"}
            ),
            spec=client.V1PodSpec(
                node_name=node,
                host_pid=True,
                restart_policy="Never",
                tolerations=[client.V1Toleration(operator="Exists")],
                containers=[
                    client.V1Container(
                        name="import",
                        image=IMPORT_HELPER_IMAGE,
                        command=["sleep", "600"],
                        security_context=client.V1SecurityContext(privileged=True),
                    )
                ],
            ),
        )
        logger.info(f"Importing {image} into node {node}")
        self.core.create_namespaced_pod(IMPORT_NAMESPACE, pod)
        try:
            self._run(
                ["kubectl", "wait", "--namespace", IMPORT_NAMESPACE, "--for=condition=Ready", f"pod/{name}"]
                + ["--timeout=120s"]
            )
            exec_command = ["kubectl", "exec", "--stdin", "--namespace", IMPORT_NAMESPACE, name, "--"]
            self._run(exec_command + ["nsenter", "-t", "1", "-m", "--", "sh", "-c", IMPORT_SCRIPT], input_path=archive)
        finally:
            self.core.delete_namespaced_pod(name, IMPORT_NAMESPACE, grace_period_seconds=0)

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


def _tools(step: DeploymentStep) -> List[str]:
    if isinstance(step, HelmRelease):
        return ["helm"]
    if isinstance(step, ImageBuild):
        return ["docker", "kubectl"] if step.delivery == "import" else ["docker"]
    return ["kubectl"]


def _require_tools(steps: Sequence[DeploymentStep]) -> None:
    tools = {tool for step in steps for tool in _tools(step)}
    missing = sorted(tool for tool in tools if shutil.which(tool) is None)
    if missing:
        raise DeploymentException(
            message=f"Missing required command line tools: {', '.join(missing)}",
            explanation="Install them and make sure they are on the PATH",
        )
