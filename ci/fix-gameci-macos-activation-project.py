#!/usr/bin/env python3
"""Preserve GameCI v0.1.48's bundled BlankProject across APK and AAB.

GameCI's macOS entrypoint removes ACTION_FOLDER/BlankProject at the end of
each build, then mkdir -p on the next invocation. mkdir makes an empty dir,
not a Unity project, so the next licensing activation aborts with
"Couldn't set project path to:" despite an activated entitlement.

Patch only the installed public GameCI CLI runner copy. No private source,
key material, unity project or original encrypted build script is touched.
Fail closed if the pinned CLI layout changes.
"""
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ENTRYPOINT = Path("dist/platforms/mac/entrypoint.sh")
PROJECT_VERSION = Path("dist/BlankProject/ProjectSettings/ProjectVersion.txt")

# Match only normal post-build cleanup; retain activation-only cleanup.
ORIGINAL = (
    '  source $ACTION_FOLDER/platforms/mac/steps/return_license.sh\n'
    '  rm -r "$ACTIVATE_LICENSE_PATH"\n'
    'fi\n'
)
FIXED = (
    '  source $ACTION_FOLDER/platforms/mac/steps/return_license.sh\n'
    '  # GameCI v0.1.48 macOS multi-build: keep its bundled valid Unity\n'
    '  # BlankProject for the next APK/AAB activation in the same job.\n'
    'fi\n'
)


def patch(root: Path) -> str:
    root = root.resolve(strict=True)
    entrypoint = root / ENTRYPOINT
    blank_project = root / PROJECT_VERSION
    if (
        entrypoint.is_symlink()
        or blank_project.is_symlink()
        or not entrypoint.is_file()
        or not blank_project.is_file()
        or not (0 < blank_project.stat().st_size < 4096)
    ):
        raise ValueError("GameCI installed project or entrypoint unavailable")
    info = entrypoint.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
        raise ValueError("GameCI macOS entrypoint invalid")
    raw = entrypoint.read_bytes()
    text = raw.decode("utf-8")
    if text.count(FIXED) == 1 and ORIGINAL not in text:
        return "already-patched"
    if text.count(ORIGINAL) != 1 or text.count(FIXED) != 0:
        raise ValueError("GameCI pinned entrypoint cleanup structure changed")
    # Guard the original activation-only branch and license return.
    if text.count('rm -r "$ACTIVATE_LICENSE_PATH"') != 2:
        raise ValueError("GameCI activation cleanup count changed")
    updated = text.replace(ORIGINAL, FIXED, 1)
    if updated.count('rm -r "$ACTIVATE_LICENSE_PATH"') != 1:
        raise ValueError("GameCI activation-only cleanup was modified")
    result = subprocess.run(
        ["bash", "-n"], input=updated, text=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False, timeout=10,
    )
    if result.returncode != 0:
        raise ValueError("GameCI patched entrypoint failed shell validation")

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(entrypoint.parent), prefix=".simple-gameci-",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), info.st_mode & 0o777)
            handle.write(updated.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, entrypoint)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return "preserve-valid-activation-project"


def main() -> int:
    try:
        # The GameCI launcher is pinned and installed into this runner-temp tree.
        root = Path(os.environ["RUNNER_TEMP"]) / "game-ci" / "bin"
        result = patch(root)
    except (OSError, ValueError, KeyError, UnicodeError, subprocess.SubprocessError):
        print(
            "GameCI macOS activation project reuse preflight failed; "
            "see encrypted diagnostics.",
            file=sys.stderr,
        )
        return 1
    print("GameCI macOS dual-build activation project: " + result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
