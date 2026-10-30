"""Exercise GameCI's macOS standard-path preflight without Unity downloads.

All tests use temporary user-writable directories; no sudo and no /Applications.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ci" / "prepare-gameci-link-macos.sh"
VERSION = "2022.3.62f3"


class GameCILinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.standard = base / "Applications" / "Unity" / "Hub" / "Editor"
        self.target = base / "private" / VERSION
        self.logs = base / "logs"
        self.logs.mkdir()

    def run_preflight(self, version=VERSION, target=None, expected_old=None):
        env = dict(os.environ)
        env.update({
            "SIMPLE_CI_LOG_DIR": str(self.logs),
            "SIMPLE_CI_LINK_ROOT": str(self.standard),
            "SIMPLE_CI_LINK_VERSION": version,
            "SIMPLE_CI_LINK_TARGET": str(self.target if target is None else target),
        })
        env.pop("SIMPLE_CI_LINK_EXPECTED_OLD_TARGET", None)
        if expected_old is not None:
            env["SIMPLE_CI_LINK_EXPECTED_OLD_TARGET"] = str(expected_old)
        return subprocess.run(
            ["bash", str(SCRIPT)], env=env, capture_output=True, text=True,
            timeout=8, check=False,
        )

    def test_prepares_dangling_symlink_before_editor_install(self):
        result = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        link = self.standard / VERSION
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(self.target))
        self.assertFalse(self.target.exists())
        self.assertIn("result=prepared", (self.logs / "gameci-path-preflight.txt").read_text())

        # The portable installer may create the Editor *later*.
        binary = self.target / "Unity.app" / "Contents" / "MacOS" / "Unity"
        android = self.target / "PlaybackEngines" / "AndroidPlayer" / "SDK"
        binary.parent.mkdir(parents=True)
        binary.write_text("unity executable placeholder")
        android.mkdir(parents=True)
        self.assertTrue((link / "Unity.app" / "Contents" / "MacOS" / "Unity").is_file())
        self.assertTrue((link / "PlaybackEngines" / "AndroidPlayer" / "SDK").is_dir())

    def test_preflight_is_idempotent(self):
        self.assertEqual(self.run_preflight().returncode, 0)
        self.assertEqual(self.run_preflight().returncode, 0)

    def test_retargets_only_link_owned_by_preflight(self):
        self.assertEqual(self.run_preflight().returncode, 0)
        alternative = self.target.with_name(VERSION + "-x86_64")
        result = self.run_preflight(target=alternative, expected_old=self.target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.standard / VERSION), str(alternative))

    def test_retarget_rejects_incorrect_previous_target(self):
        self.assertEqual(self.run_preflight().returncode, 0)
        alternative = self.target.with_name(VERSION + "-x86_64")
        result = self.run_preflight(target=alternative, expected_old=self.target.parent / "not-ours")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.readlink(self.standard / VERSION), str(self.target))

    def test_replaces_only_empty_version_directory(self):
        (self.standard / VERSION).mkdir(parents=True)
        result = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.standard / VERSION).is_symlink())

    def test_preserves_preexisting_nonempty_editor(self):
        installed = self.standard / VERSION
        installed.mkdir(parents=True)
        (installed / "important.txt").write_text("do not touch")
        result = self.run_preflight()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((installed / "important.txt").read_text(), "do not touch")
        self.assertIn("SIMPLE_CI_PHASE=unity_cli_path_conflict", result.stdout)

    def test_refuses_unknown_version_symlink(self):
        self.standard.mkdir(parents=True)
        (self.standard / VERSION).symlink_to("/tmp/unrelated-installation")
        result = self.run_preflight()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.readlink(self.standard / VERSION), "/tmp/unrelated-installation")

    def test_refuses_root_directory_symlink(self):
        self.standard.parent.mkdir(parents=True)
        self.standard.symlink_to(self.temp.name, target_is_directory=True)
        result = self.run_preflight()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("root-symlink", (self.logs / "gameci-path-preflight.txt").read_text())

    def test_refuses_malformed_version(self):
        result = self.run_preflight(version="../../malicious")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.standard.exists())


if __name__ == "__main__":
    unittest.main()
