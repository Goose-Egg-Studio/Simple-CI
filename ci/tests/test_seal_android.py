#!/usr/bin/env python3
"""Secret-free smoke tests using dummy payloads and a fake age executable.

Fake encryption is intentionally used ONLY inside isolated temporary test
directories, never in the production Android workflow.
"""
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "seal-android.py"


class SealedArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake_age = self.bin / "age"
        fake_age.write_text(
            "#!/usr/bin/env python3\n"
            "import sys, shutil\n"
            "shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer)\n",
            encoding="utf-8"
        )
        fake_age.chmod(0o755)
        self.logs = self.root / "logs"
        self.logs.mkdir()
        (self.logs / "build.log").write_text("dummy-private-test-log", encoding="utf-8")
        self.dist = self.root / "dist"
        self.dist.mkdir()
        self.output = self.root / "out"
        self.recipient = self.root / "recipient.txt"
        self.recipient.write_text("age1fakepublicrecipient", encoding="utf-8")
        self.outputs = self.root / "outputs.txt"

    def invoke(self):
        env = os.environ.copy()
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env["GITHUB_OUTPUT"] = str(self.outputs)
        return subprocess.run(
            [sys.executable, str(SCRIPT),
             "--logs", str(self.logs),
             "--dist", str(self.dist),
             "--recipient-file", str(self.recipient),
             "--out", str(self.output),
             "--run-id", "42"],
            capture_output=True, text=True, env=env, timeout=30
        )

    def read_tar(self, suffix):
        with tarfile.open(self.output / ("android-42-" + suffix + ".tar.gz.age"), "r:gz") as archive:
            return archive.getnames()

    def test_three_archives_are_independent(self):
        (self.dist / "simple.apk").write_bytes(b"FAKE-APK")
        (self.dist / "simple.aab").write_bytes(b"FAKE-AAB")
        proc = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(list(self.output.glob("*.tar.gz.age"))), 3)
        self.assertIn("build-outputs/simple.apk", self.read_tar("apk"))
        self.assertNotIn("build-outputs/simple.aab", self.read_tar("apk"))
        self.assertIn("build-outputs/simple.aab", self.read_tar("aab"))
        self.assertNotIn("build-outputs/simple.apk", self.read_tar("aab"))
        self.assertIn("private-logs/build.log", self.read_tar("logs"))
        self.assertNotIn("private-logs/build.log", self.read_tar("apk"))
        flags = self.outputs.read_text()
        self.assertIn("has_apk=true", flags)
        self.assertIn("has_aab=true", flags)
        self.assertIn("has_logs=true", flags)

    def test_failure_retains_independent_encrypted_logs(self):
        (self.dist / "simple.apk").write_bytes(b"FAKE-APK")
        proc = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(list(self.output.glob("*.tar.gz.age"))), 2)
        self.assertIn("private-logs/build.log", self.read_tar("logs"))
        flags = self.outputs.read_text()
        self.assertIn("has_apk=true", flags)
        self.assertIn("has_aab=false", flags)
        self.assertIn("has_logs=true", flags)

    def test_missing_dist_retains_diagnostics_only(self):
        self.dist.rmdir()
        proc = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(list(self.output.glob("*.tar.gz.age"))), 1)
        self.assertIn("private-logs/build.log", self.read_tar("logs"))
        self.assertIn("has_apk=false", self.outputs.read_text())
        self.assertIn("has_aab=false", self.outputs.read_text())


if __name__ == "__main__":
    unittest.main()
