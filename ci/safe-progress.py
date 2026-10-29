#!/usr/bin/env python3
"""Stream allow-listed phase notices, never unfiltered Unity output.

The full subprocess stream is written to the local private log file and later
included ONLY in the age-encrypted diagnostic artifact. Public Actions logs
get constant phase names, elapsed minutes, and constant failure categories.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

# The phase marker names are fixed strings emitted by sealed scripts.
SAFE_SCRIPT_PHASES = {
    b"SIMPLE_CI_PHASE=android_apk_start": "APK: Unity build started",
    b"SIMPLE_CI_PHASE=android_apk_done": "APK: build completed",
    b"SIMPLE_CI_PHASE=android_apk_failed": "APK: build failed",
    b"SIMPLE_CI_PHASE=android_aab_start": "AAB: Unity build started",
    b"SIMPLE_CI_PHASE=android_aab_done": "AAB: build completed",
    b"SIMPLE_CI_PHASE=android_aab_failed": "AAB: build failed",
    b"SIMPLE_CI_PHASE=android_stage_start": "Staging signed APK and AAB",
    b"SIMPLE_CI_PHASE=android_stage_done": "APK and AAB staged for encryption",
}

EDITOR_PHASES = (
    ("image", "Unity runtime preparation", (b"Pulling from unityci/editor", b"running docker process for linux", b"installing Unity Editor", b"Installing Unity Editor")),
    ("license", "Unity license activation requested", (b"Requesting activation (professional license)", b"Requesting activation (personal license)", b"Requesting activation")),
    ("license_ok", "Unity license activated successfully", (b"Activation complete.",)),
    ("project", "Unity project build entered", (b"#    Building project", b"#    Building project     #")),
    ("packages", "Unity packages resolved", (b"[Package Manager] Done resolving packages",)),
    ("assets", "Unity asset import started", (b"Application.AssetDatabase Initial Refresh Start",)),
    ("scripts", "Unity C# script compilation started", (b"[ScriptCompilation] Requested script compilation",)),
    ("buildplayer", "Unity BuildPlayer entered", (b"BuildPlayer: building player", b"BuildPlayerWindow.DefaultBuildMethods.BuildPlayer", b"Building Player",)),
    ("addressables_ok", "Encrypted Addressables verified", (b"SIMPLE_CI_ADDRESSABLES_VERIFIED",)),
    ("player_ok", "Unity Android player verified", (b"SIMPLE_CI_PLAYER_VERIFIED",)),
)

# Do not copy the matched line into stdout. Labels are fixed and independent
# of private file names, compiler diagnostics, passwords, or argument values.
FAILURE_MARKERS = (
    ("License", (b"Unclassified error occured while trying to activate license", b"License activation has failed")),
    ("C# compiler", (b"error CS",)),
    ("Android signing", (b"Unable to sign the application; please provide passwords!", b"Can not sign the application")),
    ("Addressables", (b"Addressable content build failure", b"Failed to build Addressables content", b"Addressables content build failed", b"Encrypted Addressables manifest is missing", b"Encrypted Addressables bundle missing", b"Local encrypted Addressables are absent")),
    ("Asset/video importer", (b"Asset import failed for using an unsupported file type",)),
    ("Unity crash", (b"Segmentation fault", b"Fatal error in GC", b"Caught fatal signal",)),
)


def notice(message):
    print("::notice title=Simple CI phase::" + message, flush=True)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--heartbeat", type=int, default=60)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        parser.error("missing build command")
    if args.heartbeat < 20:
        parser.error("heartbeat must be at least 20 seconds")

    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    last_ping = start
    seen_editor_phases = set()
    seen_script_phases = set()
    detected_failures = set()
    incomplete_line = b""

    def report(line):
        nonlocal seen_editor_phases
        event = line.strip()
        if event in SAFE_SCRIPT_PHASES and event not in seen_script_phases:
            seen_script_phases.add(event)
            notice(SAFE_SCRIPT_PHASES[event] + " (T+" + str(int((time.monotonic() - start) / 60)) + "m)")
            if event in (b"SIMPLE_CI_PHASE=android_apk_start", b"SIMPLE_CI_PHASE=android_aab_start"):
                seen_editor_phases.clear()
        for key, label, markers in EDITOR_PHASES:
            if key not in seen_editor_phases and any(marker in line for marker in markers):
                seen_editor_phases.add(key)
                notice(label + " (T+" + str(int((time.monotonic() - start) / 60)) + "m)")
        for key, markers in FAILURE_MARKERS:
            if any(marker in line for marker in markers):
                detected_failures.add(key)

    notice("Private Unity build launched (T+0m)")
    with path.open("wb", buffering=0) as writer:
        proc = subprocess.Popen(command, stdout=writer, stderr=subprocess.STDOUT)
        with path.open("rb", buffering=0) as reader:
            while True:
                chunk = reader.read(1024 * 1024)
                if chunk:
                    incomplete_line += chunk
                    *lines, incomplete_line = incomplete_line.split(b"\n")
                    for line in lines:
                        report(line)
                    continue
                if proc.poll() is not None:
                    if incomplete_line:
                        report(incomplete_line)
                    break
                if time.monotonic() - last_ping >= args.heartbeat:
                    notice("Unity build is still running; raw log is private (T+" +
                           str(int((time.monotonic() - start) / 60)) + "m)")
                    last_ping = time.monotonic()
                time.sleep(2)
        code = proc.wait()

    # Unity 2022.3 can return Success even when Addressables content was
    # omitted. Never publish such a Player as a successful Android build.
    if "Addressables" in detected_failures:
        print("::error title=Simple CI Addressables::Addressables content build "
              "failed. APK/AAB are incomplete even if Unity reports success. "
              "Inspect age-encrypted diagnostics.", flush=True)
        return 86

    if code == 0:
        notice("Build command completed successfully")
    else:
        labels = ", ".join(k for k, _ in FAILURE_MARKERS if k in detected_failures)
        if not labels:
            labels = "Unclassified failure"
        print("::error title=Simple CI build::Build failed (" + labels +
              "). See age-encrypted diagnostics for exact errors.", flush=True)
    return code if code >= 0 else 128 + abs(code)


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        print("::error title=Simple CI monitor::Progress monitor failed; "
              "see encrypted diagnostics.", flush=True)
        sys.exit(125)
