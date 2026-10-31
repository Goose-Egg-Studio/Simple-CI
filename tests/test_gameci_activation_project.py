"""Regression tests for GameCI's macOS APK-then-AAB license project reuse.

The v0.1.48 CLI deletes its own BlankProject after a build. A second
activation can only create an empty folder, not restore Unity metadata.
"""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gameci_activation_project",
    ROOT / "ci" / "fix-gameci-macos-activation-project.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

ENTRYPOINT_FIXTURE = """#!/usr/bin/env bash
if [ "$ACTIVATE_ONLY" = "true" ]; then
  rm -r "$ACTIVATE_LICENSE_PATH"
  exit $UNITY_EXIT_CODE
fi
if [ "$SKIP_ACTIVATION" != "true" ]; then
  source $ACTION_FOLDER/platforms/mac/steps/return_license.sh
  rm -r "$ACTIVATE_LICENSE_PATH"
fi
exit $BUILD_EXIT_CODE
"""


class GameCIActivationProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "game-ci" / "bin"
        self.dist = self.base / "dist"
        self.entrypoint = self.base / module.ENTRYPOINT
        self.project = self.base / module.PROJECT_VERSION
        self.entrypoint.parent.mkdir(parents=True)
        self.project.parent.mkdir(parents=True)
        self.entrypoint.write_text(ENTRYPOINT_FIXTURE)
        self.project.write_text("m_EditorVersion: 2022.3.62f3\n")

    def test_preserves_project_after_regular_build(self):
        self.assertEqual(module.patch(self.base), "preserve-valid-activation-project")
        self.assertEqual(module.patch(self.base), "already-patched")
        patched = self.entrypoint.read_text()
        self.assertIn(module.FIXED, patched)
        self.assertEqual(patched.count('rm -r "$ACTIVATE_LICENSE_PATH"'), 1)
        self.assertIn('if [ "$ACTIVATE_ONLY" = "true" ]', patched)
        self.assertEqual(
            subprocess.run(["bash", "-n", str(self.entrypoint)], check=False).returncode,
            0,
        )
        self.assertTrue(self.project.exists())

    def test_refuses_missing_unity_project(self):
        self.project.unlink()
        original = self.entrypoint.read_bytes()
        with self.assertRaises(ValueError):
            module.patch(self.base)
        self.assertEqual(original, self.entrypoint.read_bytes())

    def test_refuses_unfamiliar_upstream_cleanup(self):
        text = self.entrypoint.read_text()
        self.entrypoint.write_text(text.replace(
            'rm -r "$ACTIVATE_LICENSE_PATH"',
            'rm -rf "$ACTIVATE_LICENSE_PATH"',
        ))
        original = self.entrypoint.read_bytes()
        with self.assertRaises(ValueError):
            module.patch(self.base)
        self.assertEqual(original, self.entrypoint.read_bytes())

    def test_refuses_symlinked_entrypoint(self):
        target = self.entrypoint.with_name("alternate.sh")
        target.write_bytes(self.entrypoint.read_bytes())
        self.entrypoint.unlink()
        self.entrypoint.symlink_to(target)
        with self.assertRaises(ValueError):
            module.patch(self.base)

    def test_refuses_multiple_cleanup_sites(self):
        self.entrypoint.write_text(ENTRYPOINT_FIXTURE + ENTRYPOINT_FIXTURE)
        with self.assertRaises(ValueError):
            module.patch(self.base)


if __name__ == "__main__":
    unittest.main()
