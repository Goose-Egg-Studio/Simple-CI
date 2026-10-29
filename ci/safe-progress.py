#!/usr/bin/env python3
"""Report allow-listed Unity build phases; keep all raw output encrypted.

The watchdog uses its own thread, so heavy Unity output cannot starve the
heartbeat. Process names, log sizes and disk measurements are written only
to the private diagnostics directory, never to public Actions stdout.
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

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
    ("project", "Unity project build entered", (b"#    Building project",)),
    ("packages", "Unity packages resolved", (b"[Package Manager] Done resolving packages",)),
    ("assets", "Unity asset import started", (b"Application.AssetDatabase Initial Refresh Start",)),
    ("scripts", "Unity C# script compilation started", (b"[ScriptCompilation] Requested script compilation",)),
    ("buildplayer", "Unity BuildPlayer entered", (b"BuildPlayer: building player", b"BuildPlayerWindow.DefaultBuildMethods.BuildPlayer", b"Building Player")),
    ("addressables_ok", "Encrypted Addressables verified", (b"SIMPLE_CI_ADDRESSABLES_VERIFIED",)),
    ("player_ok", "Unity Android player verified", (b"SIMPLE_CI_PLAYER_VERIFIED",)),
)
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


def detect_processes():
    """Read executable names, never process arguments (which could hold secrets)."""
    try:
        raw = subprocess.check_output(
            ["ps", "-A", "-o", "comm="],
            stderr=subprocess.DEVNULL, timeout=8
        ).decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return "unknown", "unknown", "unknown"
    names = [Path(line.strip()).name.lower() for line in raw.splitlines()]
    unity = any(n == "unity" or n.startswith("unity.") for n in names)
    hub = any("unity hub" in n or n.startswith("unityhub") for n in names)
    cli = any(n.startswith("game-ci") for n in names)
    return ("yes" if unity else "no",
            "yes" if hub else "no",
            "yes" if cli else "no")


def stop_process(proc):
    """Stop all children of the sealed shell, not just its direct parent."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            proc.terminate()
        except ProcessLookupError:
            pass


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--heartbeat", type=int, default=60)
    parser.add_argument("--stall-minutes", type=int, default=35)
    parser.add_argument("--max-minutes", type=int, default=115)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        parser.error("missing build command")
    if args.heartbeat < 5 or args.stall_minutes < 1 or args.max_minutes <= args.stall_minutes:
        parser.error("invalid watchdog thresholds")

    path = Path(args.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    private_monitor = path.parent / "unity-watchdog.log"
    start = time.monotonic()
    stop = threading.Event()
    lock = threading.Lock()
    state = {"last_output": start, "total_bytes": 0, "abort": ""}
    seen_editor_phases = set()
    seen_script_phases = set()
    detected_failures = set()
    incomplete_line = b""

    def report(line):
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

    def watchdog(proc):
        low_disk_samples = 0
        try:
            with private_monitor.open("a", encoding="utf-8") as diag:
                while not stop.wait(args.heartbeat):
                    now = time.monotonic()
                    with lock:
                        idle = now - state["last_output"]
                        output_bytes = state["total_bytes"]
                    try:
                        space = shutil.disk_usage(str(path.parent))
                        free_gib = space.free / (1024 ** 3)
                        disk = "low" if free_gib < 2.0 else "ok"
                    except OSError:
                        free_gib, disk = -1.0, "unknown"
                    editor, hub, cli = detect_processes()
                    diag.write(
                        "elapsed_s={:.0f} idle_s={:.0f} bytes={} free_gib={:.2f} "
                        "editor={} hub={} gameci={}\n".format(
                            now - start, idle, output_bytes, free_gib, editor, hub, cli
                        )
                    )
                    diag.flush()
                    notice(
                        "Unity build heartbeat (T+{}m; disk={}; editor={}; "
                        "hub={}; log={})".format(
                            int((now - start) / 60), disk,
                            "seen" if editor == "yes" else "not-seen",
                            "seen" if hub == "yes" else "not-seen",
                            "idle" if idle >= args.heartbeat * 2 else "active"
                        )
                    )
                    if 0 <= free_gib < 1.0:
                        low_disk_samples += 1
                    else:
                        low_disk_samples = 0
                    reason = ""
                    if low_disk_samples >= 3:
                        reason = "disk-pressure"
                    elif idle >= args.stall_minutes * 60:
                        reason = "no-log-growth"
                    elif now - start >= args.max_minutes * 60:
                        reason = "hard-build-timeout"
                    if reason and proc.poll() is None:
                        with lock:
                            state["abort"] = reason
                        diag.write("watchdog_abort=" + reason + "\n")
                        diag.flush()
                        print(
                            "::error title=Simple CI watchdog::Build stopped: "
                            + reason + ". See age-encrypted diagnostics.",
                            flush=True
                        )
                        stop_process(proc)
                        return
        except Exception:
            # Never print a raw exception (may contain a private path).
            print("::warning title=Simple CI watchdog::Monitoring error; check encrypted diagnostics.", flush=True)

    notice("Private Unity build launched (T+0m)")
    with path.open("wb", buffering=0) as writer:
        proc = subprocess.Popen(
            command, stdout=writer, stderr=subprocess.STDOUT,
            start_new_session=True
        )
        worker = threading.Thread(target=watchdog, args=(proc,), daemon=True)
        worker.start()
        try:
            with path.open("rb", buffering=0) as reader:
                while True:
                    chunk = reader.read(1024 * 1024)
                    if chunk:
                        with lock:
                            state["last_output"] = time.monotonic()
                            state["total_bytes"] += len(chunk)
                        incomplete_line += chunk
                        *lines, incomplete_line = incomplete_line.split(b"\n")
                        for line in lines:
                            report(line)
                        # Protect memory if a tool prints an unterminated giant line.
                        incomplete_line = incomplete_line[-65536:]
                        continue
                    if proc.poll() is not None:
                        if incomplete_line:
                            report(incomplete_line)
                        break
                    time.sleep(1)
            code = proc.wait()
        finally:
            stop.set()
            worker.join(timeout=10)

    if state["abort"]:
        return 124
    if "Addressables" in detected_failures:
        print(
            "::error title=Simple CI Addressables::Content build failed; "
            "APK/AAB must not be released. See encrypted diagnostics.",
            flush=True
        )
        return 86
    if code == 0:
        notice("Build command completed successfully")
    else:
        labels = ", ".join(k for k, _ in FAILURE_MARKERS if k in detected_failures)
        if not labels:
            labels = "Unclassified failure"
        print(
            "::error title=Simple CI build::Build failed (" + labels
            + "). See age-encrypted diagnostics.", flush=True
        )
    return code if code >= 0 else 128 + abs(code)


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        print(
            "::error title=Simple CI monitor::Progress monitor failed; "
            "see encrypted diagnostics.", flush=True
        )
        sys.exit(125)
