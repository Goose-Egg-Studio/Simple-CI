#!/usr/bin/env python3
"""Apply one audited compatibility fix to the decrypted macOS Android CI C#.

Unity Run #35 reported CS0103 at SimpleCISealedMacAndroid.cs:29, column 13.
The official Addressables 1.22 API belongs to UnityEditor.AddressableAssets,
not UnityEditor.AddressableAssets.Settings. The sealed implementation is
private; adjust its *ephemeral, decrypted runner copy only*, before GameCI
imports it. This does not modify user project sources or disclose the C#.
"""
import argparse
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

IDENTIFIER = "AddressableAssetSettingsDefaultObject"
QUALIFIED = "UnityEditor.AddressableAssets." + IDENTIFIER
BARE = re.compile(r"(?<![A-Za-z0-9_.])" + IDENTIFIER + r"\b")
KNOWN_FAILURE_LINE = 29


def patch(path: Path, runner_temp: Path) -> str:
    expected_root = runner_temp.resolve(strict=True) / "secure-ci" / "scripts"
    # Never rewrite a symlink, arbitrary repo path, or more than the single
    # CI helper that this error actually names.
    if path.name != "SimpleCISealedMacAndroid.cs":
        raise ValueError("unexpected target filename")
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or symlinked decrypted C# helper")
    if path.parent.resolve(strict=True) != expected_root:
        raise ValueError("decrypted helper is outside temporary secure-ci scripts")
    info = path.stat()
    if not (0 < info.st_size < 512 * 1024) or not stat.S_ISREG(info.st_mode):
        raise ValueError("invalid decrypted C# helper size/type")

    original = path.read_bytes()
    try:
        code = original.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("decrypted C# helper is not valid UTF-8") from exc

    lines = code.splitlines(keepends=True)
    if len(lines) < KNOWN_FAILURE_LINE:
        raise ValueError("sealed helper layout changed unexpectedly")
    line = lines[KNOWN_FAILURE_LINE - 1]
    if not BARE.search(line):
        if QUALIFIED in line:
            return "already-qualified"
        raise ValueError("known CS0103 source line changed; refusing blind rewrite")

    # Line-specific fix: the compiler's actual error location is known.
    # Avoid modifying comments, other unrelated code or the sealed shell.
    patched_line, count = BARE.subn(QUALIFIED, line)
    if count != 1:
        raise ValueError("ambiguous Addressables reference on known error line")
    lines[KNOWN_FAILURE_LINE - 1] = patched_line
    updated = "".join(lines).encode("utf-8")
    if original.startswith(b"\xef\xbb\xbf"):
        updated = b"\xef\xbb\xbf" + updated
    if updated == original:
        raise ValueError("no change performed")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(path.parent), prefix=".addressables-fix-",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            os.fchmod(handle.fileno(), info.st_mode & 0o777)
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return "qualified-CS0103-symbol"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    args = parser.parse_args()
    try:
        runner_temp = Path(os.environ["RUNNER_TEMP"])
        result = patch(Path(args.path), runner_temp)
    except (OSError, ValueError, KeyError):
        print("Sealed Android Addressables compatibility check failed; "
              "inspect private logs.", file=sys.stderr)
        return 1
    # Only a fixed state is public. Never print source content or paths.
    print("Sealed Android Addressables API reference: " + result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
