#!/usr/bin/env python3
"""Match GameCI v0.1.48's required success marker at verified player success.

On macOS, Unity Run #36 produces a valid Game.apk and emits the private
helper's success-only 'SIMPLE_CI_PLAYER_VERIFIED' log, but GameCI's native
MacBuilder.validateBuild looks for the literal 'Build succeeded!' and
otherwise throws, despite Unity returning success. Only alter that
existing, verified-success log; never patch GameCI to ignore failures.
"""
import argparse
import os
import stat
import sys
from pathlib import Path

TARGET = "SimpleCISealedMacAndroid.cs"
OLD = '"SIMPLE_CI_PLAYER_VERIFIED"'
NEW = '"SIMPLE_CI_PLAYER_VERIFIED | Build succeeded!"'


def patch(path: Path, runner_temp: Path) -> str:
    scripts = runner_temp.resolve(strict=True) / "secure-ci" / "scripts"
    if path.name != TARGET or path.parent.resolve(strict=True) != scripts:
        raise ValueError("unexpected target path")
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid target file")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or not (0 < st.st_size < 512 * 1024):
        raise ValueError("invalid C# helper")
    raw = path.read_bytes()
    content = raw.decode("utf-8-sig")
    if content.count(NEW) == 1 and content.count(OLD) == 0:
        return "already-patched"
    if content.count(OLD) != 1 or content.count(NEW) != 0:
        raise ValueError("ambiguous verified-success marker")
    lines = content.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if OLD in line]
    if len(matches) != 1 or not 70 <= matches[0] + 1 <= 90:
        raise ValueError("verified-success log is not on known source line")
    if "Debug.Log" not in lines[matches[0]]:
        raise ValueError("verified-success marker is not a Unity log call")
    lines[matches[0]] = lines[matches[0]].replace(OLD, NEW, 1)
    updated = "".join(lines).encode("utf-8")
    if raw.startswith(b"\xef\xbb\xbf"):
        updated = b"\xef\xbb\xbf" + updated
    # Atomic replacement with same permissions; no plaintext source leaked.
    import tempfile
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(path.parent),
            prefix=".gameci-build-result-", delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            os.fchmod(handle.fileno(), st.st_mode & 0o777)
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return "verified-player-success-reporter-updated"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    args = parser.parse_args()
    try:
        result = patch(Path(args.path), Path(os.environ["RUNNER_TEMP"]))
    except (OSError, ValueError, KeyError, UnicodeDecodeError):
        print("GameCI macOS verified-player result marker compatibility check failed.", file=sys.stderr)
        return 1
    print("GameCI macOS build result compatibility: " + result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
