"""Unit tests for Unity's private activity signals and bounded hang collection."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ci"))
import unity_health


class UnityHealthTests(unittest.TestCase):
    def test_mac_cpu_time_formats(self):
        self.assertEqual(unity_health.cpu_seconds("00:01.50"), 1.5)
        self.assertEqual(unity_health.cpu_seconds("01:02:03.25"), 3723.25)
        self.assertEqual(unity_health.cpu_seconds("2-03:04:05.00"), 2*86400 + 3*3600 + 4*60 + 5)
        self.assertIsNone(unity_health.cpu_seconds("not-a-time"))

    def test_classify_editor_and_workers_without_exposing_paths(self):
        self.assertEqual(
            unity_health.classify_command("/runner/editor/Unity.app/Contents/MacOS/Unity"),
            "editor",
        )
        self.assertEqual(
            unity_health.classify_command("/tmp/simple-unity-cli/bin/unity"),
            "cli",
        )
        self.assertEqual(
            unity_health.classify_command("/app/AssetImportWorker.0"),
            "worker",
        )
        self.assertEqual(unity_health.classify_command("/usr/bin/bash"), "other")

    def test_cpu_delta_counts_real_cpu_progress(self):
        self.assertEqual(unity_health.cpu_delta({100: 2.0}, {100: 5.5}), 3.5)
        self.assertEqual(unity_health.cpu_delta({100: 5.5}, {100: 5.5}), 0.0)
        self.assertEqual(unity_health.cpu_delta({100: 5.5}, {101: 2.0}), 2.0)
        self.assertIsNone(unity_health.cpu_delta(None, {}))

    def test_editor_log_growth_without_reading_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            logs = base / "Library" / "Logs" / "Unity"
            logs.mkdir(parents=True)
            first = unity_health.unity_log_stamps(base)
            self.assertEqual(first, {})
            (logs / "Editor.log").write_text("secret build paths")
            later = unity_health.unity_log_stamps(base)
            self.assertTrue(unity_health.log_changed(first, later))
            self.assertFalse(unity_health.log_changed(later, later))
            (logs / "Editor.log").write_text("secret build paths\nnext event")
            final = unity_health.unity_log_stamps(base)
            self.assertTrue(unity_health.log_changed(later, final))

    def test_diagnostics_collector_writes_only_inside_private_log_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            logs = temp / "simple-private-logs"
            logs.mkdir()
            editor = temp / "home" / "Library" / "Logs" / "Unity"
            editor.mkdir(parents=True)
            (editor / "Editor.log").write_text("PRIVATE_EDITOR_DIAGNOSTIC")
            env = dict(os.environ, RUNNER_TEMP=str(temp), HOME=str(temp / "home"))
            args = [sys.executable, str(ROOT / "ci" / "capture-unity-hang.py"),
                    "--dir", str(logs), "--tag", "unit-test", "--pgid", str(os.getpid())]
            run = subprocess.run(args, env=env, capture_output=True, text=True, timeout=12)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertNotIn("PRIVATE_EDITOR_DIAGNOSTIC", run.stdout)
            self.assertTrue((logs / "unity-hang-unit-test" / "snapshot.json").is_file())
            self.assertIn(
                b"PRIVATE_EDITOR_DIAGNOSTIC",
                (logs / "unity-hang-unit-test" / "unity-log-00.tail").read_bytes(),
            )
            bad = subprocess.run(
                [sys.executable, str(ROOT / "ci" / "capture-unity-hang.py"),
                 "--dir", str(temp), "--tag", "invalid", "--pgid", "1"],
                env=env, capture_output=True, text=True, timeout=12,
            )
            self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
