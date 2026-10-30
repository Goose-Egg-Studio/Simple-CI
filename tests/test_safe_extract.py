"""Security tests for decrypt-and-extract of private CI script bundles."""
import io
import stat
import sys
import tarfile
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
safe = SourceFileLoader(
    "safe_extract", str(ROOT / "ci" / "safe-extract.py")
).load_module()


class TestSafeExtraction(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "scripts.tar.gz"
        self.dest = self.root / "out"

    def pack(self, members):
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, data, kind in members:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.mode = 0o755
                if kind == tarfile.REGTYPE:
                    payload = data.encode()
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))
                elif kind == tarfile.SYMTYPE:
                    member.linkname = data
                    archive.addfile(member)
                else:
                    archive.addfile(member)

    def test_valid_script_preserves_executability_and_privacy(self):
        self.pack([
            ("scripts/", "", tarfile.DIRTYPE),
            ("scripts/checkout-source.sh", "#!/bin/sh\nexit 0\n", tarfile.REGTYPE),
        ])
        safe.extract(self.archive, self.dest)
        script = self.dest / "scripts/checkout-source.sh"
        self.assertTrue(script.is_file())
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
        self.assertFalse(script.stat().st_mode & stat.S_IROTH)

    def test_two_archives_can_overlay_regular_files(self):
        self.pack([("scripts/build.sh", "old", tarfile.REGTYPE)])
        safe.extract(self.archive, self.dest)
        self.pack([("scripts/build.sh", "new", tarfile.REGTYPE)])
        safe.extract(self.archive, self.dest)
        self.assertEqual((self.dest / "scripts/build.sh").read_text(), "new")

    def test_reject_traversal_without_partial_extraction(self):
        self.pack([
            ("scripts/good.sh", "okay", tarfile.REGTYPE),
            ("../leak.txt", "secret", tarfile.REGTYPE),
        ])
        with self.assertRaises(ValueError):
            safe.extract(self.archive, self.dest)
        self.assertFalse((self.dest / "scripts/good.sh").exists())
        self.assertFalse((self.root / "leak.txt").exists())

    def test_reject_absolute_paths(self):
        self.pack([("/tmp/unsafe", "bad", tarfile.REGTYPE)])
        with self.assertRaises(ValueError):
            safe.extract(self.archive, self.dest)

    def test_reject_archive_symlink(self):
        self.pack([("scripts/link", "../../outside", tarfile.SYMTYPE)])
        with self.assertRaises(ValueError):
            safe.extract(self.archive, self.dest)

    def test_reject_existing_symlink_parent(self):
        self.dest.mkdir()
        (self.dest / "scripts").symlink_to(self.root, target_is_directory=True)
        self.pack([("scripts/target.sh", "bad", tarfile.REGTYPE)])
        with self.assertRaises(ValueError):
            safe.extract(self.archive, self.dest)
        self.assertFalse((self.root / "target.sh").exists())

    def test_reject_duplicate_archive_paths(self):
        self.pack([
            ("scripts/a", "1", tarfile.REGTYPE),
            ("scripts/a", "2", tarfile.REGTYPE),
        ])
        with self.assertRaises(ValueError):
            safe.extract(self.archive, self.dest)


if __name__ == "__main__":
    unittest.main()
