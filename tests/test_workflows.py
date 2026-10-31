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
        for filename in ("android.yml", "ios.yml", "ci-audit.yml", "macos-gameci-preflight.yml"):
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

    def test_macos_android_module_path_is_sibling_of_unity_app(self):
        # Regression for the 2026-10-30 false-negative AndroidPlayer checks.
        # Unity's macOS Editor binary is inside Unity.app/Contents, but the
        # Android module is installed alongside the .app bundle.
        installer = (ROOT / "ci" / "preinstall-unity-macos.sh").read_text(
            encoding="utf-8"
        )
        snapshot = (ROOT / "ci" / "capture-unity-hub.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'LOCAL_ANDROID="$EDITOR_DIR/PlaybackEngines/AndroidPlayer"',
            installer,
        )
        self.assertIn(
            'ANDROID="$STANDARD_ROOT/$VERSION/PlaybackEngines/AndroidPlayer"',
            installer,
        )
        self.assertNotIn(
            "Unity.app/Contents/PlaybackEngines/AndroidPlayer",
            installer,
        )
        self.assertIn(
            'android_root = editor_root.parent.parent / "PlaybackEngines" / "AndroidPlayer"',
            snapshot,
        )

    def test_gameci_link_preflight_occurs_before_any_unity_download(self):
        installer = (ROOT / "ci" / "preinstall-unity-macos.sh").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            installer.index("bash ci/ci/prepare-gameci-link-macos.sh"),
            installer.index("https://unity.com/install.sh"),
        )
        self.assertLess(
            installer.index("SIMPLE_CI_PHASE=unity_cli_path_start"),
            installer.index("run_cli_stage editor install"),
        )
        self.assertIn("SIMPLE_CI_PHASE=unity_cli_gameci_path_verified", installer)
        self.assertIn("test -d \"$ANDROID/SDK\"", installer)
        self.assertIn("test -d \"$ANDROID/NDK\"", installer)
        self.assertIn("test -d \"$ANDROID/OpenJDK\"", installer)

    def test_real_macos_path_probe_is_secretless_and_editor_free(self):
        probe = self.read("macos-gameci-preflight.yml")
        self.assertIn("runs-on: macos-26-intel", probe)
        self.assertIn("ci/prepare-gameci-link-macos.sh", probe)
        self.assertIn("workflow_dispatch:", probe)
        self.assertNotIn("secrets.", probe)
        self.assertNotIn("unity install", probe)
        self.assertNotIn("brew install", probe)
        self.assertIn("PlaybackEngines/AndroidPlayer/SDK", probe)

    def test_native_build_uses_multi_signal_watchdog_and_private_stacks(self):
        android = self.read("android.yml")
        self.assertIn("--max-no-output 1800", android)
        self.assertIn("--diagnose-after 600", android)
        self.assertIn("--max-no-phase 3600", android)
        self.assertIn("--max-no-output 2700", android)  # independent CLI install
        monitor = (ROOT / "ci" / "safe-progress.py").read_text(encoding="utf-8")
        self.assertIn("unity_health.unity_log_stamps()", monitor)
        self.assertIn("unity_health.cpu_delta(", monitor)
        self.assertIn("private_unity_snapshot(\"console-stall\")", monitor)
        self.assertIn("private_unity_snapshot(\"watchdog\")", monitor)
        snapshot = (ROOT / "ci" / "capture-unity-hang.py").read_text(encoding="utf-8")
        self.assertIn("sample", snapshot)
        self.assertIn("simple-private-logs", snapshot)
        self.assertNotIn("print(raw.stdout", snapshot)

    def test_android_outputs_are_separately_encrypted(self):
        text = self.read("android.yml")
        self.assertIn("android-apk-sealed-", text)
        self.assertIn("android-aab-sealed-", text)
        self.assertIn("android-logs-sealed-", text)
        self.assertIn("ci/ci/artifact-recipient.txt", text)

    def test_temporary_log_key_is_public_only_and_separate_from_products(self):
        android, ios = self.read("android.yml"), self.read("ios.yml")
        log_recipient = (ROOT / "ci" / "log-recipient.txt").read_text(
            encoding="utf-8"
        ).strip()
        product_recipient = (ROOT / "ci" / "artifact-recipient.txt").read_text(
            encoding="utf-8"
        ).strip()
        source_recipient = (ROOT / "ci" / "recipient.txt").read_text(
            encoding="utf-8"
        ).strip()
        self.assertRegex(log_recipient, r"^age1[0-9a-z]+$")
        self.assertNotIn("AGE-SECRET-KEY", log_recipient)
        self.assertNotEqual(log_recipient, product_recipient)
        self.assertNotEqual(log_recipient, source_recipient)

        for kind in ("apk", "aab"):
            self.assertIn("python3 ci/ci/seal-android.py --kind " + kind + " |", android)
        self.assertEqual(android.count("ci/ci/log-recipient.txt"), 1)
        self.assertEqual(android.count("ci/ci/artifact-recipient.txt"), 2)
        self.assertIn("ios-logs-sealed-", ios)
        self.assertIn("ios-sealed-", ios)
        self.assertEqual(ios.count("ci/ci/log-recipient.txt"), 1)
        self.assertEqual(ios.count("ci/ci/artifact-recipient.txt"), 1)
        self.assertNotIn("tf.add(logs, arcname='private-logs')", ios)
        self.assertIn("age -r", ios)

        self.assertIn("tf.add(artifacts, arcname='build-outputs')", ios)
        self.assertIn("steps.seal_ios_logs.outcome == 'success'", ios)
        self.assertIn("steps.seal_ios_outputs.outputs.sealed == 'true'", ios)

    def test_audit_workflow_has_no_secret_dependency(self):
        text = self.read("ci-audit.yml")
        self.assertNotIn("secrets.", text)
        self.assertIn("python3 -m unittest discover", text)


if __name__ == "__main__":
    unittest.main()
