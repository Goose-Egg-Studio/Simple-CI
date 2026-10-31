"""Smoke tests for public progress redaction and noninteractive exit handling."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "ci" / "safe-progress.py"


class ProgressTests(unittest.TestCase):
    def invoke(self, platform, script):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "private.log"
            health = Path(tmp) / "health.jsonl"
            process = subprocess.run(
                [
                    sys.executable, "-u", str(MONITOR),
                    "--platform", platform,
                    "--log", str(log),
                    "--health-log", str(health),
                    "--heartbeat", "20",
                    "--", sys.executable, "-c", script,
                ],
                text=True, capture_output=True, timeout=15, check=False,
            )
            return process, log.read_text(errors="replace")

    def test_android_phase_is_public_but_raw_output_is_private(self):
        process, private = self.invoke(
            "android",
            "print('SIMPLE_CI_PHASE=unity_cli_editor_start', flush=True); "
            "print('PRIVATE_TOKEN_SHOULD_NOT_APPEAR', flush=True)"
        )
        self.assertEqual(process.returncode, 0, process.stdout)
        self.assertIn("Unity Editor and Android modules bundled installation started", process.stdout)
        self.assertIn("PRIVATE_TOKEN_SHOULD_NOT_APPEAR", private)
        self.assertNotIn("PRIVATE_TOKEN_SHOULD_NOT_APPEAR", process.stdout)
        self.assertNotIn("PRIVATE_TOKEN_SHOULD_NOT_APPEAR", process.stderr)

    def test_missing_unity_android_payload_has_explicit_failure_category(self):
        process, private = self.invoke(
            "android",
            "import sys; "
            "print('SIMPLE_CI_PHASE=unity_cli_android_payload_absent', flush=True); "
            "print('PRIVATE_MODULE_INSTALL_OUTPUT', flush=True); "
            "sys.exit(37)",
        )
        self.assertEqual(process.returncode, 37)
        self.assertIn("Unity Android payload absent after bundled install", process.stdout)
        self.assertIn("Build failed (Unity Android components)", process.stdout)
        self.assertIn("PRIVATE_MODULE_INSTALL_OUTPUT", private)
        self.assertNotIn("PRIVATE_MODULE_INSTALL_OUTPUT", process.stdout)

    def test_invalid_project_path_is_not_misreported_as_license_failure(self):
        process, private = self.invoke(
            "android",
            "import sys; "
            "print(\"Couldn't set project path to:\", flush=True); "
            "print('Unclassified error occured while trying to activate license.', flush=True); "
            "sys.exit(1)",
        )
        self.assertEqual(process.returncode, 1)
        self.assertIn("Build failed (Unity project path)", process.stdout)
        self.assertNotIn("Build failed (License)", process.stdout)
        self.assertIn("Couldn't set project path to:", private)
        self.assertNotIn("Couldn't set project path to:", process.stdout)

    def test_ios_silences_raw_errors_but_preserves_exit(self):
        process, private = self.invoke(
            "ios",
            "import sys;print('PRIVATE_IOS_ERROR', flush=True);sys.exit(7)"
        )
        self.assertEqual(process.returncode, 7)
        self.assertIn("Private iOS build launched", process.stdout)
        self.assertIn("Build failed (Unclassified failure)", process.stdout)
        self.assertIn("PRIVATE_IOS_ERROR", private)
        self.assertNotIn("PRIVATE_IOS_ERROR", process.stdout)


if __name__ == "__main__":
    unittest.main()
