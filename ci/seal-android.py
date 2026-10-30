#!/usr/bin/env python3
"""Stream exactly one Android payload or private logs into a gzip tar for age.

Never print raw paths or private names. The caller pipes this directly into age;
no plaintext tar file is placed in the public workspace.
"""
import argparse
import os
import sys
import tarfile
import zipfile
from pathlib import Path


def validate_android_package(file, kind):
    """Reject truncated/incorrect ZIPs before publishing a sealed artifact.

    This is only a structural gate. Gameplay resources and signatures must
    still be verified by the sealed Unity build before this script is called.
    """
    manifest = "AndroidManifest.xml" if kind == "apk" else "base/manifest/AndroidManifest.xml"
    try:
        with zipfile.ZipFile(file, "r") as package:
            member = package.getinfo(manifest)
            if member.is_dir() or member.file_size == 0 or member.file_size > 8 * 1024 * 1024:
                raise RuntimeError("invalid Android manifest")
            with package.open(member) as source:
                if not source.read(1):
                    raise RuntimeError("unreadable Android manifest")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise RuntimeError("Android archive does not contain a readable manifest") from exc


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("apk", "aab", "logs"), required=True)
    args = parser.parse_args()
    workspace = Path(os.environ["GITHUB_WORKSPACE"])
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz", compresslevel=1) as archive:
        if args.kind in ("apk", "aab"):
            dist = workspace / "dist"
            if not dist.is_dir():
                raise RuntimeError("missing output directory")
            candidates = list(dist.rglob("*." + args.kind))
            if len(candidates) != 1:
                raise RuntimeError("expected exactly one build artifact")
            file = candidates[0]
            if file.is_symlink() or any(parent.is_symlink() for parent in file.parents if parent != dist.parent):
                raise RuntimeError("symlinked output")
            if not file.is_file() or file.stat().st_size == 0 or not file.resolve().is_relative_to(dist.resolve()):
                raise RuntimeError("invalid build artifact")
            validate_android_package(file, args.kind)
            archive.add(file, arcname="build-outputs/Simple." + args.kind, recursive=False)
        else:
            root = Path(os.environ["RUNNER_TEMP"]) / "simple-private-logs"
            root.mkdir(parents=True, exist_ok=True)
            archive.add(root, arcname="private-logs", recursive=False)
            for parent, dirs, files in os.walk(root, followlinks=False):
                base = Path(parent)
                dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink())
                for name in dirs:
                    item = base / name
                    archive.add(item, arcname=str(Path("private-logs") / item.relative_to(root)), recursive=False)
                for name in sorted(files):
                    item = base / name
                    if item.is_file() and not item.is_symlink():
                        archive.add(item, arcname=str(Path("private-logs") / item.relative_to(root)), recursive=False)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        print("Simple CI: sealed archive input validation failed (details withheld)", file=sys.stderr)
        sys.exit(1)
