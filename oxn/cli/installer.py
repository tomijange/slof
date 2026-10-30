"""
Purpose: Guides the user through preparing a cluster for experiments (oxn setup).
Functionality: Checks the command line tools and the current cluster, then walks through OpenEBS, Prometheus and
    Kepler: shows what is already there, what would be installed and with which command, and asks before installing.
Connection: Called by main.py. Reuses the helm release handling of deployment.py. Everything else an experiment
    needs is installed by the deployment section of its spec.
"""
import json
import os
import shlex
import shutil
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from oxn.common.errors import DeploymentException
from oxn.orchestration.deployment import CommandRunner, HelmRelease, run_command

READY = "ready"
MISSING = "missing"
CONFLICT = "conflict"

REQUIRED_COMMANDS = {
    "kubectl": "https://kubernetes.io/docs/tasks/tools/ (macOS: brew install kubernetes-cli)",
    "helm": "https://helm.sh/docs/intro/install/ (macOS: brew install helm)",
}
"""Command line tools oxn needs, with a hint on how to get them"""


@dataclass
class Tool:
    """A tool that stays on the cluster between experiments"""

    name: str
    purpose: str
    release: HelmRelease
    provided: Optional[List[str]] = None
    """kubectl resource (kind and name) whose existence means experiments have what they need from this tool"""
    requires: Optional[str] = None
    """Name of a tool that must be on the cluster before this one can be installed"""
    note: str = ""


TOOLS = [
    Tool(
        name="OpenEBS",
        purpose="Provides the openebs-hostpath StorageClass that the SUE's volumes request.",
        release=HelmRelease(
            release="openebs",
            chart="openebs",
            repo="https://openebs.github.io/openebs",
            version="4.6.2",
            namespace="openebs",
            set={
                "engines.local.lvm.enabled": False,
                "engines.local.zfs.enabled": False,
                "engines.replicated.mayastor.enabled": False,
                "loki.enabled": False,
                "alloy.enabled": False,
                "localpv-provisioner.hostpathClass.isDefaultClass": True,
            },
        ),
        provided=["storageclass", "openebs-hostpath"],
    ),
    Tool(
        name="Prometheus",
        purpose="kube-prometheus-stack stores the metrics that oxn reads as experiment results.",
        release=HelmRelease(
            release="kube-prometheus",
            chart="kube-prometheus-stack",
            repo="https://prometheus-community.github.io/helm-charts",
            version="92.16.1",
            namespace="oxn-external-monitoring",
            values=["deployments/values/values_kube_prometheus.yaml"],
        ),
        provided=["crd", "servicemonitors.monitoring.coreos.com"],
        note="Experiment specs deploy and remove this release for every run. Installing it here puts the "
        "ServiceMonitor CRD on the cluster, which stays after teardown and which Kepler needs.",
    ),
    Tool(
        name="Kepler",
        purpose="Exports the energy metrics of pods and containers.",
        release=HelmRelease(
            release="kepler",
            chart="oci://quay.io/sustainable_computing_io/charts/kepler",
            version="0.12.0",
            namespace="oxn-external-monitoring",
            values=["deployments/values/values_kepler.yaml"],
        ),
        requires="Prometheus",
        note="Runs privileged on every node and needs real hardware energy counters (RAPL) to report anything.",
    ),
]
"""The tools to install, in the order they depend on each other"""


def chart_name(chart: str) -> str:
    """The bare name of a chart reference like oci://quay.io/charts/kepler"""
    return chart.rsplit("/", 1)[-1]


class Installer:
    """Interactive installation of the tools that stay on the cluster between experiments"""

    def __init__(
        self,
        yes: bool = False,
        dry_run: bool = False,
        tools: Optional[List[Tool]] = None,
        run: CommandRunner = run_command,
        ask: Callable[[str], str] = input,
    ):
        self.yes = yes
        """Install everything that is missing without asking"""
        self.dry_run = dry_run
        """Only report what is installed and what would run"""
        self.tools = TOOLS if tools is None else tools
        self._run = run
        self._ask = ask
        self._releases: List[dict] = []

    def run(self) -> int:
        """Walk through all tools. Returns the exit code: 1 if something needs the user's attention."""
        try:
            if not self._check_prerequisites():
                return 1
            outcomes = self._install_tools()
        except KeyboardInterrupt:
            print("\nAborted, nothing else was changed.")
            return 1
        self._print_summary(outcomes)
        return 1 if any(outcome in ("failed", "conflict") for outcome in outcomes.values()) else 0

    def _check_prerequisites(self) -> bool:
        print("oxn setup prepares a cluster for experiments. Experiment specs deploy the SUE themselves;")
        print("this installs the tools they need around it.\n")

        missing = [command for command in REQUIRED_COMMANDS if shutil.which(command) is None]
        for command in missing:
            print(f"Missing {command}, install it first: {REQUIRED_COMMANDS[command]}")
        if missing:
            return False

        values = [path for tool in self.tools for path in tool.release.values if not os.path.exists(path)]
        if values:
            print(f"Cannot find {', '.join(values)}. Run oxn setup from the repository root.")
            return False

        try:
            context = self._run(["kubectl", "config", "current-context"]).strip()
            self._run(["kubectl", "get", "namespaces", "-o", "name", "--request-timeout=10s"])
            self._releases = json.loads(self._run(["helm", "list", "--all-namespaces", "--output", "json"]) or "[]")
        except DeploymentException as e:
            print(f"Cannot talk to the cluster: {e}")
            return False

        print(f"Cluster: {context}")
        if self.dry_run or self.yes:
            return True
        return self._confirm("Install into this cluster?", default=False)

    def _install_tools(self) -> Dict[str, str]:
        """Go through the tools in order and return what happened to each of them"""
        outcomes: Dict[str, str] = {}
        for index, tool in enumerate(self.tools, start=1):
            print(f"\n[{index}/{len(self.tools)}] {tool.name}: {tool.purpose}")
            if tool.note:
                print(f"  {tool.note}")
            status, detail = self._status(tool)
            print(f"  Status: {detail}")
            outcomes[tool.name] = self._handle(tool, status, outcomes)
        return outcomes

    def _handle(self, tool: Tool, status: str, outcomes: Dict[str, str]) -> str:
        if status == READY:
            return "ready"
        if status == CONFLICT:
            return "conflict"
        if tool.requires and outcomes.get(tool.requires) not in ("ready", "installed", "would install"):
            print(f"  Skipping, {tool.name} needs {tool.requires} on the cluster first.")
            return "skipped"

        command = tool.release.install_command()
        print(f"  $ {shlex.join(command)}")
        if self.dry_run:
            return "would install"
        if not self.yes and not self._confirm(f"Install {tool.name}?", default=True):
            return "skipped"

        print(f"  Installing {tool.name}, this can take several minutes...")
        try:
            self._run(command)
        except DeploymentException as e:
            print(f"  Failed: {e}")
            return "failed"
        print(f"  Installed {tool.name}.")
        return "installed"

    def _status(self, tool: Tool) -> Tuple[str, str]:
        if tool.provided and self._exists(tool.provided):
            return READY, f"{' '.join(tool.provided)} found, nothing to do"

        release = tool.release
        existing = next(
            (r for r in self._releases if r["chart"].rsplit("-", 1)[0] == chart_name(release.chart)),
            None,
        )
        if existing is None:
            return MISSING, "not installed"

        location = f"{existing['namespace']}/{existing['name']}"
        if (existing["namespace"], existing["name"]) != (release.namespace, release.release):
            return (
                CONFLICT,
                f"{existing['chart']} is installed as {location}, oxn expects {release.namespace}/{release.release}. "
                "Leaving it alone, a second install would run the tool twice. Remove it to continue.",
            )
        if tool.provided:
            return (
                CONFLICT,
                f"{existing['chart']} is installed as {location}, but {' '.join(tool.provided)} is missing. "
                "Leaving it alone, upgrading would replace its settings. Fix it by hand, see docs/tools/.",
            )
        if existing["status"] != "deployed":
            return MISSING, f"{existing['chart']} is installed but its status is {existing['status']}"
        return READY, f"{existing['chart']} is installed, nothing to do"

    def _exists(self, resource: List[str]) -> bool:
        try:
            self._run(["kubectl", "get", *resource, "-o", "name"])
            return True
        except DeploymentException:
            return False

    def _confirm(self, question: str, default: bool) -> bool:
        choices = "Y/n" if default else "y/N"
        try:
            answer = self._ask(f"  {question} [{choices}] ").strip().lower()
        except EOFError:
            print("\n  No terminal to ask on, treating that as no. Use --yes for scripts.")
            return False
        return answer in ("y", "yes") if answer else default

    def _print_summary(self, outcomes: Dict[str, str]) -> None:
        print("\nSummary")
        for name, outcome in outcomes.items():
            print(f"  {name:<12}{outcome}")
        if self.dry_run:
            print("\nThis was a dry run, nothing was changed.")
            return
        if not all(outcome in ("ready", "installed") for outcome in outcomes.values()):
            return
        print("\nThe cluster is ready. Run an experiment; its spec deploys the SUE and removes it afterwards:")
        print("  mkdir -p reports")
        print("  oxn experiments/test.yml --report reports/")
