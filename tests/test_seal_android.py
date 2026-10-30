"""Android package shape checks; no real Unity project is needed."""
import tempfile
import unittest
import zipfile
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
seal = SourceFileLoader("seal_android", str(ROOT / "ci" / "seal-android.py")).load_module()


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def package(self, kind, names):
        file = self.root / ("Simple." + kind)
        with zipfile.ZipFile(file, "w", compression=zipfile.ZIP_STORED) as bundle:
            for name in names:
                bundle.writestr(name, b"abc")
        return file

    def test_android_apk_has_manifest(self):
        seal.validate_android_package(
            self.package("apk", ["AndroidManifest.xml", "classes.dex"]), "apk"
        )

    def test_android_aab_has_base_manifest(self):
        seal.validate_android_package(
            self.package("aab", ["base/manifest/AndroidManifest.xml"]), "aab"
        )

    def test_reject_nonzip_file(self):
        file = self.root / "fake.apk"
        file.write_bytes(b"not an apk")
        with self.assertRaises(RuntimeError):
            seal.validate_android_package(file, "apk")

    def test_reject_missing_manifest(self):
        with self.assertRaises(RuntimeError):
            seal.validate_android_package(self.package("apk", ["assets/dummy"]), "apk")

    def test_reject_empty_manifest(self):
        file = self.root / "empty.apk"
        with zipfile.ZipFile(file, "w") as bundle:
            bundle.writestr("AndroidManifest.xml", b"")
        with self.assertRaises(RuntimeError):
            seal.validate_android_package(file, "apk")


if __name__ == "__main__":
    unittest.main()
