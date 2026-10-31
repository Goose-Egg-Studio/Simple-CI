#!/usr/bin/env python3
"""Bounded macOS 26 IconServices probe and temporary-runner workaround.

GitHub actions/runner-images#14751: macOS 26 Intel iconservicesagent can
crash-loop in Metal; Unity's NSWorkspace iconForFileType hangs forever
during the first AssetDatabase refresh. Never execute Unity on an affected
runner until the same file-icon API returns after mitigation.

Only the current *ephemeral* runner user's launchd GUI service is affected.
No private source, credentials or network operations are needed.
"""
import os
import platform
import subprocess
import sys
from pathlib import Path

SERVICE = "com.apple.iconservices.iconservicesagent"
SOURCE = Path(__file__).with_name("probe-macos-iconservices.swift")


def invoke(args, log, timeout):
    try:
        with log.open("ab") as output:
            result = subprocess.run(
                args, stdout=output, stderr=subprocess.STDOUT,
                timeout=timeout, check=False,
            )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        # A short, private error classification; never echo command output.
        with log.open("a", encoding="utf-8") as output:
            output.write("command-error=" + type(exc).__name__ + "\n")
        return False


def run():
    private = Path(os.environ["SIMPLE_CI_LOG_DIR"])
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = private / "iconservices-preflight.log"
    report = private / "iconservices-preflight-status.txt"
    if platform.system() != "Darwin":
        print("IconServices preflight skipped: not macOS.")
        return 0

    mac_version = platform.mac_ver()[0]
    if mac_version.split(".", 1)[0] != "26":
        print("IconServices preflight skipped: macOS 26 workaround not applicable.")
        return 0

    runner_temp = Path(os.environ["RUNNER_TEMP"])
    binary = runner_temp / "simple-iconservices-probe"
    with report.open("w", encoding="utf-8") as output:
        output.write("platform=macos26\n")

    # A standalone Swift probe is faster and more specific than a full Unity
    # launch. First-run compilation has a finite cap; all output is private.
    if not invoke(["xcrun", "swiftc", str(SOURCE), "-o", str(binary)], log, 120):
        with report.open("a") as output:
            output.write("probe-compile=failed\n")
        print("::error title=Simple CI IconServices::Cannot compile macOS file-icon preflight; see encrypted diagnostics.")
        return 81

    if invoke([str(binary)], log, 12):
        with report.open("a") as output:
            output.write("initial-probe=passed\n")
        print("::notice title=Simple CI IconServices::macOS file-icon request healthy.")
        return 0

    with report.open("a") as output:
        output.write("initial-probe=failed-or-stalled\n")
    print("::notice title=Simple CI IconServices::macOS file-icon request stalled; applying per-runner workaround.")

    # Observed remedy in actions/runner-images#14751. bootout may report a
    # missing service when the agent has already crashed; always attempt both.
    # No sudo, no system-wide modifications, only GUI domain for current UID.
    unit = "gui/%d/%s" % (os.getuid(), SERVICE)
    booted_out = invoke(["launchctl", "bootout", unit], log, 15)
    disabled = invoke(["launchctl", "disable", unit], log, 15)
    with report.open("a") as output:
        output.write("bootout=%s\n" % ("ok" if booted_out else "unavailable"))
        output.write("disable=%s\n" % ("ok" if disabled else "unavailable"))

    # Fail closed: only proceed if the exact API that froze Unity has now
    # returned successfully. Don't waste 60 minutes building on speculation.
    if not invoke([str(binary)], log, 12):
        with report.open("a") as output:
            output.write("post-mitigation-probe=failed-or-stalled\n")
        print("::error title=Simple CI IconServices::macOS icon service workaround failed verification; build aborted before Unity download.")
        return 82

    with report.open("a") as output:
        output.write("post-mitigation-probe=passed\n")
    print("::notice title=Simple CI IconServices::macOS icon request healthy after per-runner workaround.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (OSError, ValueError, KeyError):
        print("::error title=Simple CI IconServices::macOS icon preflight failed; inspect encrypted diagnostics.")
        sys.exit(83)
