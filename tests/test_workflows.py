"""Regression checks for public CI workflow boundaries without external packages."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class WorkflowSecurityTests(unittest.TestCase):
    def read(self, name):
        return (WORKFLOWS / name).read_text(encoding="utf-8")

    def test_all_public_actions_have_immutable_sha(self):
        for filename in ("android.yml", "ios.yml", "ci-audit.yml"):
            text = self.read(filename)
            actions = re.findall(r"^\s*uses:\s*(actions/[^\s#]+)", text, re.M)
            self.assertTrue(actions, filename)
            for action in actions:
                self.assertRegex(action, r"^actions/[\w-]+@[a-f0-9]{40}$")

    def test_decrypted_archives_use_bounded_safe_extractor(self):
        android, ios = self.read("android.yml"), self.read("ios.yml")
        for text in (android, ios):
            self.assertIn('python3 ci/ci/safe-extract.py --archive "$TMP"', text)
            self.assertNotIn('tar -xzf "$TMP"', text)
        self.assertIn('python3 ci/ci/safe-extract.py --archive "$MAC_TMP"', android)
        self.assertNotIn('tar -xzf "$MAC_TMP"', android)

    def test_ios_build_uses_private_monitor(self):
        ios = self.read("ios.yml")
        self.assertIn("ci/ci/safe-progress.py", ios)
        self.assertIn("--platform ios", ios)
        self.assertIn("health-ios.jsonl", ios)
        self.assertNotIn('cli-build-ios.sh" > "$RUNNER_TEMP/simple-private-logs/unity-build.log"', ios)

    def test_untrusted_editor_installer_precedes_private_checkout(self):
        android = self.read("android.yml")
        self.assertLess(android.index("Preinstall Unity Editor"), android.index("Unseal CI implementation"))
        self.assertLess(android.index("Preinstall Unity Editor"), android.index("Checkout private Unity source"))
        self.assertLess(android.index("Install GameCI CLI privately"), android.index("Preinstall Unity Editor"))
        self.assertLess(self.read("ios.yml").index("Install GameCI CLI privately"), self.read("ios.yml").index("Unseal CI implementation"))

    def test_private_build_workflows_are_dispatch_only(self):
        for filename in ("android.yml", "ios.yml"):
            text = self.read(filename)
            self.assertIn("workflow_dispatch:", text)
            self.assertIn("github.ref_name == github.event.repository.default_branch", text)
            self.assertIn("github.actor", text)
            self.assertIn("github.triggering_actor", text)
            self.assertIn("permission-contents: read", text)
            self.assertIn("persist-credentials: false", text)
            self.assertIn("python3 ci/ci/validate-source-ref.py", text)
            self.assertLess(text.index("Validate selected private source ref"), text.index("Generate read-only source token"))

    def test_portable_unity_install_bundles_android_support(self):
        installer = (ROOT / "ci" / "preinstall-unity-macos.sh").read_text(
            encoding="utf-8"
        )
        start = installer.index("run_cli_stage editor install")
        validate = installer.index("SIMPLE_CI_PHASE=unity_cli_modules_validate_start")
        stage = installer[start:validate]
        self.assertIn('--download-directory "$WRITABLE_ROOT"', stage)
        self.assertIn("--module android --child-modules", stage)
        self.assertNotIn("run_cli_stage modules install-modules", stage)
        self.assertIn("if [[ -d \"$LOCAL_ANDROID\" ]]", installer)
        self.assertIn("SIMPLE_CI_PHASE=unity_cli_android_payload_absent", installer)
        self.assertIn("unity-android-module-locations.txt", installer)

    def test_android_outputs_are_separately_encrypted(self):
        text = self.read("android.yml")
        self.assertIn("android-apk-sealed-", text)
        self.assertIn("android-aab-sealed-", text)
        self.assertIn("android-logs-sealed-", text)
        self.assertIn("ci/ci/artifact-recipient.txt", text)

    def test_audit_workflow_has_no_secret_dependency(self):
        text = self.read("ci-audit.yml")
        self.assertNotIn("secrets.", text)
        self.assertIn("python3 -m unittest discover", text)


if __name__ == "__main__":
    unittest.main()
