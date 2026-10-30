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
        self.assertIn("Standalone Unity Editor core install started", process.stdout)
        self.assertIn("PRIVATE_TOKEN_SHOULD_NOT_APPEAR", private)
        self.assertNotIn("PRIVATE_TOKEN_SHOULD_NOT_APPEAR", process.stdout)
        self.assertNotIn("PRIVATE_TOKEN_SHOULD_NOT_APPEAR", process.stderr)

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
