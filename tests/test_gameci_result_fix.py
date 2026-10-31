"""The macOS GameCI output validator recognizes only a success marker with !."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gameci_result_fix", ROOT / "ci" / "fix-sealed-macos-gameci-result.py"
)
fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)


class ResultMarkerTests(unittest.TestCase):
    def setup_target(self, base, marker=True):
        root = Path(base)
        target = root / "secure-ci" / "scripts" / "SimpleCISealedMacAndroid.cs"
        target.parent.mkdir(parents=True)
        lines = ["// placeholder" for _ in range(100)]
        if marker:
            lines[79] = '        Debug.Log("SIMPLE_CI_PLAYER_VERIFIED");'
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target

    def test_verified_player_marker_updates_gameci_result(self):
        with tempfile.TemporaryDirectory() as td:
            target = self.setup_target(td)
            self.assertEqual(fix.patch(target, Path(td)),
                             "verified-player-success-reporter-updated")
            content = target.read_text()
            self.assertIn("SIMPLE_CI_PLAYER_VERIFIED | Build succeeded!", content)
            self.assertEqual(content.count("Build succeeded!"), 1)
            self.assertEqual(fix.patch(target, Path(td)), "already-patched")

    def test_missing_verified_marker_does_not_make_false_success(self):
        with tempfile.TemporaryDirectory() as td:
            target = self.setup_target(td, marker=False)
            before = target.read_bytes()
            with self.assertRaises(ValueError):
                fix.patch(target, Path(td))
            self.assertEqual(before, target.read_bytes())

    def test_marker_outside_known_success_section_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            target = self.setup_target(td)
            lines = target.read_text().splitlines()
            lines[79] = "// line 80 changed"
            lines[10] = 'Debug.Log("SIMPLE_CI_PLAYER_VERIFIED");'
            target.write_text("\n".join(lines) + "\n")
            with self.assertRaises(ValueError):
                fix.patch(target, Path(td))


if __name__ == "__main__":
    unittest.main()
