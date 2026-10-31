"""Unit coverage for macOS 26 IconServices headless-Unity mitigation.

Runs on Linux without launchctl, Swift or modifying the host. The actual
AppKit probe is exercised by the separate macOS Intel workflow.
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "iconservices_preflight", ROOT / "ci" / "preflight-iconservices-macos.py"
)
icon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icon)


class IconServicesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.private = self.root / "simple-private-logs"
        self.environ = patch.dict(os.environ, {
            "SIMPLE_CI_LOG_DIR": str(self.private),
            "RUNNER_TEMP": str(self.root),
        })
        self.environ.start()
        self.addCleanup(self.environ.stop)
        self.patch_platform = patch.object(icon.platform, "system", return_value="Darwin")
        self.patch_version = patch.object(icon.platform, "mac_ver", return_value=("26.6.1", ("", "", ""), ""))
        self.patch_platform.start()
        self.patch_version.start()
        self.addCleanup(self.patch_platform.stop)
        self.addCleanup(self.patch_version.stop)

    def statuses(self):
        return (self.private / "iconservices-preflight-status.txt").read_text()

    def test_healthy_agent_requires_no_launchctl(self):
        with patch.object(icon, "invoke", side_effect=[True, True]) as call:
            self.assertEqual(icon.run(), 0)
            self.assertEqual(call.call_count, 2)
            self.assertFalse(any("launchctl" in c.args[0] for c in call.call_args_list))
            self.assertIn("initial-probe=passed", self.statuses())

    def test_stalled_icon_request_disables_only_user_agent_and_rechecks(self):
        with patch.object(icon, "invoke", side_effect=[True, False, True, True, True]) as call:
            self.assertEqual(icon.run(), 0)
            args = [c.args[0] for c in call.call_args_list]
            unit = "gui/%d/%s" % (os.getuid(), icon.SERVICE)
            self.assertEqual(args[2], ["launchctl", "bootout", unit])
            self.assertEqual(args[3], ["launchctl", "disable", unit])
            self.assertIn("post-mitigation-probe=passed", self.statuses())

    def test_remediation_without_successful_probe_fails_closed(self):
        with patch.object(icon, "invoke", side_effect=[True, False, False, True, False]):
            self.assertEqual(icon.run(), 82)
            self.assertIn("post-mitigation-probe=failed-or-stalled", self.statuses())

    def test_probe_compile_failure_stops_before_unity(self):
        with patch.object(icon, "invoke", return_value=False) as call:
            self.assertEqual(icon.run(), 81)
            self.assertEqual(call.call_count, 1)
            self.assertIn("probe-compile=failed", self.statuses())

    def test_non_affected_macos_does_not_modify_icon_service(self):
        with patch.object(icon.platform, "mac_ver", return_value=("15.8", ("", "", ""), "")):
            with patch.object(icon, "invoke") as call:
                self.assertEqual(icon.run(), 0)
                call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
