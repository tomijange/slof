import json
import unittest
from unittest import mock

from oxn.cli.installer import Installer, TOOLS
from oxn.common.errors import DeploymentException


class InstallerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.commands = []
        self.existing = set()
        self.releases = []
        self.failing_install = None
        for target, value in (
            ("oxn.cli.installer.shutil.which", "/usr/bin/tool"),
            ("oxn.cli.installer.os.path.exists", True),
            ("builtins.print", None),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, command):
        self.commands.append(command)
        if command[:2] == ["kubectl", "config"]:
            return "test-context\n"
        if command[:2] == ["helm", "list"]:
            return json.dumps(self.releases)
        if command[:2] == ["kubectl", "get"] and command[2] != "namespaces" and command[3] not in self.existing:
            raise DeploymentException(message="not found")
        if command[:2] == ["helm", "upgrade"] and command[3] == self.failing_install:
            raise DeploymentException(message="install failed")
        return ""

    def _installer(self, answers=(), **kwargs):
        answers = iter(answers)
        return Installer(run=self._run, ask=lambda _: next(answers), **kwargs)

    def _installed(self):
        return [command[3] for command in self.commands if command[:2] == ["helm", "upgrade"]]

    def _release(self, name, namespace, chart, status="deployed"):
        return {"name": name, "namespace": namespace, "chart": chart, "status": status}

    def test_it_installs_everything_on_an_empty_cluster_in_order(self):
        self.assertEqual(self._installer(yes=True).run(), 0)
        self.assertEqual(self._installed(), ["openebs", "kube-prometheus", "kepler"])

    def test_it_asks_for_the_cluster_first_and_defaults_to_no(self):
        self.assertEqual(self._installer(answers=[""]).run(), 1)
        self.assertEqual(self._installed(), [])

    def test_it_installs_what_the_user_confirms(self):
        self.assertEqual(self._installer(answers=["y", "n", "", ""]).run(), 0)
        self.assertEqual(self._installed(), ["kube-prometheus", "kepler"])

    def test_kepler_is_skipped_without_prometheus(self):
        self.assertEqual(self._installer(answers=["y", "y", "n"]).run(), 0)
        self.assertEqual(self._installed(), ["openebs"])

    def test_it_skips_what_is_already_there(self):
        self.existing = {"openebs-hostpath", "servicemonitors.monitoring.coreos.com"}
        self.releases = [self._release("kepler", "oxn-external-monitoring", "kepler-0.12.0")]
        self.assertEqual(self._installer(yes=True).run(), 0)
        self.assertEqual(self._installed(), [])

    def test_it_repairs_a_failed_release(self):
        self.existing = {"openebs-hostpath", "servicemonitors.monitoring.coreos.com"}
        self.releases = [self._release("kepler", "oxn-external-monitoring", "kepler-0.12.0", status="failed")]
        self.assertEqual(self._installer(yes=True).run(), 0)
        self.assertEqual(self._installed(), ["kepler"])

    def test_it_leaves_a_release_in_another_namespace_alone(self):
        self.existing = {"openebs-hostpath", "servicemonitors.monitoring.coreos.com"}
        self.releases = [self._release("kepler", "kepler", "kepler-0.11.1")]
        self.assertEqual(self._installer(yes=True).run(), 1)
        self.assertEqual(self._installed(), [])

    def test_it_does_not_reconfigure_an_openebs_without_the_storage_class(self):
        self.releases = [self._release("openebs", "openebs", "openebs-4.6.2")]
        self.assertEqual(self._installer(yes=True).run(), 1)
        self.assertEqual(self._installed(), ["kube-prometheus", "kepler"])

    def test_dry_run_changes_nothing_and_does_not_ask(self):
        self.assertEqual(self._installer(dry_run=True).run(), 0)
        self.assertEqual(self._installed(), [])

    def test_it_reports_failures_and_stops_dependents(self):
        self.failing_install = "kube-prometheus"
        self.assertEqual(self._installer(yes=True).run(), 1)
        self.assertEqual(self._installed(), ["openebs", "kube-prometheus"])

    def test_it_stops_when_a_command_line_tool_is_missing(self):
        with mock.patch("oxn.cli.installer.shutil.which", return_value=None):
            self.assertEqual(self._installer(yes=True).run(), 1)
        self.assertEqual(self.commands, [])

    def test_it_stops_outside_the_repository(self):
        with mock.patch("oxn.cli.installer.os.path.exists", return_value=False):
            self.assertEqual(self._installer(yes=True).run(), 1)
        self.assertEqual(self.commands, [])

    def test_it_stops_when_the_cluster_is_unreachable(self):
        def unreachable(command):
            raise DeploymentException(message="connection refused")

        self.assertEqual(Installer(run=unreachable, yes=True).run(), 1)

    def test_a_closed_terminal_counts_as_no(self):
        def closed(_):
            raise EOFError

        self.assertEqual(Installer(run=self._run, ask=closed).run(), 1)
        self.assertEqual(self._installed(), [])

    def test_interrupting_a_prompt_exits_cleanly(self):
        def interrupted(_):
            raise KeyboardInterrupt

        self.assertEqual(Installer(run=self._run, ask=interrupted).run(), 1)

    def test_the_catalog_matches_the_documented_install_order(self):
        self.assertEqual([tool.name for tool in TOOLS], ["OpenEBS", "Prometheus", "Kepler"])
