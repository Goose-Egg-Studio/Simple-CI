"""Ensure each GitHub Actions inline bash block parses without downloading Unity.

This catches subtle broken heredoc pipelines before a macOS job starts.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def scripts(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        match = re.match(r"^( *)(?:run):\s*\|\s*$", lines[i])
        if not match:
            i += 1
            continue
        indent = len(match.group(1))
        code = []
        i += 1
        while i < len(lines):
            line = lines[i]
            if line.strip():
                line_indent = len(line) - len(line.lstrip(" "))
                if line_indent <= indent:
                    break
            code.append(line)
            i += 1
        nonempty = [len(line) - len(line.lstrip(" ")) for line in code if line.strip()]
        if nonempty:
            base = min(nonempty)
            yield "\n".join(line[base:] if line.strip() else "" for line in code) + "\n"


class InlineBashSyntaxTests(unittest.TestCase):
    def test_all_workflow_bash_scripts_parse(self):
        total = 0
        for path in ROOT.glob("*.yml"):
            for index, script in enumerate(scripts(path), 1):
                with self.subTest(workflow=path.name, script=index):
                    result = subprocess.run(
                        ["bash", "-n"], input=script, capture_output=True,
                        text=True, timeout=5, check=False
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                total += 1
        self.assertGreaterEqual(total, 10)


if __name__ == "__main__":
    unittest.main()
