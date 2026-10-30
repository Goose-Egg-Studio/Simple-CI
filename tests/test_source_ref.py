"""Safe source-ref input grammar and shell metacharacter regression tests."""
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
validator = SourceFileLoader(
    "validate_source_ref", str(ROOT / "ci" / "validate-source-ref.py")
).load_module()


class RefTests(unittest.TestCase):
    def test_allowed_branches_tags_and_sha(self):
        for value in ("main", "develop", "release/1.3.0", "v1.3.0",
                      "feature/cosmetic_fix", "a" * 40, "DEADBEEF" * 5):
            with self.subTest(value=value):
                self.assertTrue(validator.valid_ref(value))

    def test_reject_shell_and_git_special_references(self):
        for value in ("", "-b", "HEAD", "refs/heads/main", "remotes/origin/main",
                      "../main", "a/../b", "a//b", "main.", "a.lock",
                      "a/b.lock", "foo@{1}", "$(curl bad)", "main;echo secret",
                      "main\necho secret", "a b", "foo:bar", "x\\y",
                      "main^", "v1*", ".hidden", "branch\\rname"):
            with self.subTest(value=value):
                self.assertFalse(validator.valid_ref(value))


if __name__ == "__main__":
    unittest.main()
