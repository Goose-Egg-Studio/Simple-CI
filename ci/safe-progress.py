#!/usr/bin/env python3
"""Emit only allow-listed phase/status events while preserving private Unity logs.

This runner-side monitor never prints, uploads, or interpolates source log lines.
All subprocess stdout/stderr goes exclusively into the age-encrypted diagnostics
pipeline; stdout here contains constant messages and elapsed durations only.
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

PHASES = (
    ("image", "Preparing Unity container", (b"Pulling from unityci/editor", b"running docker process for linux")),
    ("license", "Online license activation requested", (b"Requesting activation (professional license)",)),
    ("license_ok", "Unity license activated", (b"Activation complete.",)),
    ("project", "Unity project build started", (b"#    Building project",)),
    ("packages", "Unity packages resolved", (b"[Package Manager] Done resolving packages",)),
    ("assets", "Unity asset import started", (b"Application.AssetDatabase Initial Refresh Start",)),
    ("scripts", "Unity script compilation started", (b"[ScriptCompilation] Requested script compilation",)),
)

# Literal, fixed-category diagnostics only. Never print any matched bytes.
FAILURE_MARKERS = (
    ("License activation", (b"Unclassified error occured while trying to activate license", b"License activation has failed")),
    ("C# compilation", (b"error CS",)),
    ("Android signing", (b"Unable to sign the application; please provide passwords!", b"Can not sign the application")),
    ("Addressables content", (b"Addressable content build failure", b"Failed to build Addressables content")),
    ("Asset/media import", (b"Asset import failed for using an unsupported file type",)),
)

def notice(message):
    print("::notice title=Simple CI phase::" + message, flush=True)

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--heartbeat", type=int, default=60)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing build command")
    if args.heartbeat < 20:
        parser.error("heartbeat must be at least 20 seconds")

    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    last_ping = start
    seen_phases = set()
    detected_failures = set()
    pending = b""

    notice("Build process launched; Unity details are private (T+0m)")
    with path.open("wb", buffering=0) as log_writer:
        process = subprocess.Popen(command, stdout=log_writer, stderr=subprocess.STDOUT)

        with path.open("rb", buffering=0) as log_reader:
            while True:
                chunk = log_reader.read(1024 * 1024)
                if chunk:
                    pending += chunk
                    *lines, pending = pending.split(b"\n")
                    for line in lines:
                        # A line may include Unity paths, signing arguments or IDs.
                        # Only fixed phrases from PHASES can ever reach stdout.
                        for key, label, markers in PHASES:
                            if key not in seen_phases and any(marker in line for marker in markers):
                                seen_phases.add(key)
                                notice(label + " (T+" + str(int((time.monotonic() - start) / 60)) + "m)")
                        for key, markers in FAILURE_MARKERS:
                            if any(marker in line for marker in markers):
                                detected_failures.add(key)
                    continue

                if process.poll() is not None:
                    if pending:
                        for key, markers in FAILURE_MARKERS:
                            if any(marker in pending for marker in markers):
                                detected_failures.add(key)
                    break

                if time.monotonic() - last_ping >= args.heartbeat:
                    notice("Build still running; raw logs remain sealed (T+" +
                           str(int((time.monotonic() - start) / 60)) + "m)")
                    last_ping = time.monotonic()
                time.sleep(2)

        return_code = process.wait()

    if return_code == 0:
        notice("GameCI build command completed successfully")
    else:
        # No raw lines, filenames, credentials or user-controlled strings.
        labels = ", ".join(name for name, _ in FAILURE_MARKERS if name in detected_failures)
        if not labels:
            labels = "Unclassified build failure"
        print("::error title=Simple CI build::Build command failed. "
              "Detected category: " + labels +
              ". Read age-encrypted diagnostics for details.", flush=True)
    return return_code if return_code >= 0 else 128 + abs(return_code)

if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        # Keep exception details out of public logs (they may contain paths).
        print("::error title=Simple CI monitor::Progress monitor failed; "
              "check encrypted diagnostics.", flush=True)
        sys.exit(125)
