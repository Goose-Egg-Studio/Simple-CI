#!/usr/bin/env python3
"""Keep unfiltered Unity output private while reporting safe, independent health events."""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

SAFE_SCRIPT_PHASES = {
    b"SIMPLE_CI_PHASE=unity_cli_bootstrap_start": "Standalone Unity CLI bootstrap started",
    b"SIMPLE_CI_PHASE=unity_cli_bootstrap_done": "Standalone Unity CLI installed",
    b"SIMPLE_CI_PHASE=unity_cli_path_start": "GameCI compatibility Editor symlink creation started",
    b"SIMPLE_CI_PHASE=unity_cli_path_done": "GameCI compatibility Editor symlink validated",
    b"SIMPLE_CI_PHASE=unity_cli_path_failure": "GameCI Editor compatibility path preparation failed",
    b"SIMPLE_CI_PHASE=unity_cli_download_directory_unsupported": "Unity CLI self-contained installation is unsupported",
    b"SIMPLE_CI_PHASE=unity_cli_editor_start": "Standalone Unity Editor core install started",
    b"SIMPLE_CI_PHASE=unity_cli_elevation_retry": "Unity CLI requesting noninteractive administrator retry",
    b"SIMPLE_CI_PHASE=unity_cli_elevation_unavailable": "Unity CLI administrator privileges unavailable",
    b"SIMPLE_CI_PHASE=unity_cli_invalid_arguments": "Unity CLI command argument validation failed",
    b"SIMPLE_CI_PHASE=unity_cli_release_unavailable": "Unity Editor release metadata unavailable",
    b"SIMPLE_CI_PHASE=unity_cli_elevation_failure": "Unity CLI installation administrator authorization failed",
    b"SIMPLE_CI_PHASE=unity_cli_install_failed": "Unity CLI installation exited unsuccessfully",
    b"SIMPLE_CI_PHASE=unity_cli_editor_done": "Standalone Unity Editor core install completed",
    b"SIMPLE_CI_PHASE=unity_cli_editor_path_invalid": "Unity Editor installation path validation failed",
    b"SIMPLE_CI_PHASE=unity_cli_modules_start": "Android SDK NDK OpenJDK module install started",
    b"SIMPLE_CI_PHASE=unity_cli_modules_done": "Android SDK NDK OpenJDK module install completed",
    b"SIMPLE_CI_PHASE=unity_cli_validated": "Unity Editor and Android components verified",
    b"SIMPLE_CI_PHASE=android_apk_start": "APK build requested",
    b"SIMPLE_CI_PHASE=android_apk_done": "APK build completed",
    b"SIMPLE_CI_PHASE=android_apk_failed": "APK build failed",
    b"SIMPLE_CI_PHASE=android_aab_start": "AAB build requested",
    b"SIMPLE_CI_PHASE=android_aab_done": "AAB build completed",
    b"SIMPLE_CI_PHASE=android_aab_failed": "AAB build failed",
    b"SIMPLE_CI_PHASE=android_stage_start": "Android output staging started",
    b"SIMPLE_CI_PHASE=android_stage_done": "Android outputs staged",
}
EDITOR_PHASES = (
    ("editor", "Unity Editor preparation observed", (b"installing Unity Editor", b"Installing Unity Editor")),
    ("license", "Unity license activation requested", (b"Requesting activation (professional license)", b"Requesting activation (personal license)", b"Requesting activation")),
    ("license_ok", "Unity license activated", (b"Activation complete.",)),
    ("project", "Unity project build entered", (b"#    Building project",)),
    ("packages", "Unity packages resolved", (b"[Package Manager] Done resolving packages",)),
    ("assets", "Unity asset import observed", (b"Application.AssetDatabase Initial Refresh Start",)),
    ("scripts", "Unity C# compilation observed", (b"[ScriptCompilation] Requested script compilation",)),
    ("player", "Unity player build observed", (b"BuildPlayer: building player", b"BuildPlayerWindow.DefaultBuildMethods.BuildPlayer", b"Building Player")),
    ("addressables_ok", "Encrypted Addressables verified", (b"SIMPLE_CI_ADDRESSABLES_VERIFIED",)),
    ("player_ok", "Unity Android player verified", (b"SIMPLE_CI_PLAYER_VERIFIED",)),
)
FAILURE_MARKERS = (
    ("Unity CLI install", (b"SIMPLE_CI_PHASE=unity_cli_invalid_arguments", b"SIMPLE_CI_PHASE=unity_cli_release_unavailable", b"SIMPLE_CI_PHASE=unity_cli_elevation_failure", b"SIMPLE_CI_PHASE=unity_cli_install_failed", b"SIMPLE_CI_PHASE=unity_cli_elevation_unavailable", b"SIMPLE_CI_PHASE=unity_cli_path_failure", b"SIMPLE_CI_PHASE=unity_cli_download_directory_unsupported")),
    ("License", (b"Unclassified error occured while trying to activate license", b"License activation has failed")),
    ("C# compiler", (b"error CS",)),
    ("Android signing", (b"Unable to sign the application; please provide passwords!", b"Can not sign the application")),
    ("Addressables", (b"Addressable content build failure", b"Failed to build Addressables content", b"Addressables content build failed", b"Encrypted Addressables manifest is missing", b"Encrypted Addressables bundle missing", b"Local encrypted Addressables are absent")),
    ("Asset/video importer", (b"Asset import failed for using an unsupported file type",)),
    ("Unity crash", (b"Segmentation fault", b"Fatal error in GC", b"Caught fatal signal")),
)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--health-log", required=True)
    parser.add_argument("--heartbeat", type=int, default=60)
    parser.add_argument("--max-no-phase", type=int, default=7200)
    parser.add_argument("--max-no-output", type=int, default=2700)
    parser.add_argument("--min-free-gib", type=float, default=1.5)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.heartbeat < 20:
        parser.error("invalid command or heartbeat")

    path = Path(args.log)
    health_path = Path(args.health_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    health_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    state = {"phase": "startup", "phase_time": start, "log_time": start, "progress_time": start}
    seen_editor = set()
    seen_script = set()
    failures = set()
    stop = threading.Event()
    write_lock = threading.Lock()
    timeout_reason = []

    def notice(message):
        with write_lock:
            print("::notice title=Simple CI::" + message, flush=True)

    def terminate_group(proc):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return

            # A hung Unity child may ignore SIGTERM; avoid losing diagnostics
            # by waiting indefinitely in proc.wait() after the watchdog fires.
            def force_kill():
                time.sleep(12)
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            threading.Thread(target=force_kill, name="simple-force-kill", daemon=True).start()

    def mark_phase(label):
        state["phase"] = label
        state["phase_time"] = time.monotonic()
        notice(label + " (T+" + str(int((state["phase_time"] - start) / 60)) + "m)")

    def report(line):
        event = line.strip()
        if event in SAFE_SCRIPT_PHASES and event not in seen_script:
            seen_script.add(event)
            mark_phase(SAFE_SCRIPT_PHASES[event])
            if event in (b"SIMPLE_CI_PHASE=android_apk_start", b"SIMPLE_CI_PHASE=android_aab_start"):
                seen_editor.clear()
        for key, label, markers in EDITOR_PHASES:
            if key not in seen_editor and any(token in line for token in markers):
                seen_editor.add(key)
                mark_phase(label)
        for label, markers in FAILURE_MARKERS:
            if any(token in line for token in markers):
                failures.add(label)

    def process_counts():
        try:
            result = subprocess.run(["ps", "-axo", "comm="], capture_output=True, timeout=5, check=True)
            names = [os.path.basename(x.decode("utf-8", "replace")).lower() for x in result.stdout.splitlines()]
            # "Unity Hub" and its helpers are NOT the Unity Editor.
            # Counting every name containing "unity" previously claimed that
            # Unity Editor was alive when the installer alone was running.
            editor = sum(n == "unity" for n in names)
            hub = sum(n.startswith("unity hub") or n.startswith("unityhub") for n in names)
            gameci = sum("game-ci" in n or "gameci" in n for n in names)
            return editor, hub, gameci
        except (OSError, subprocess.SubprocessError):
            return -1, -1, -1

    def hub_temp_bytes():
        # Unity Hub downloads to the macOS temporary directory by default.
        # Observe total bytes only; do not retain or print private file paths.
        # This is best-effort (Hub versions may use a different directory).
        root = Path(tempfile.gettempdir())
        total = 0
        seen = 0
        try:
            for candidate in root.glob("unityhub*"):
                if candidate.is_symlink():
                    continue
                if candidate.is_file():
                    total += candidate.stat().st_size
                    continue
                if not candidate.is_dir():
                    continue
                for parent, directories, files in os.walk(candidate, followlinks=False):
                    directories[:] = [d for d in directories if not (Path(parent) / d).is_symlink()]
                    for name in files:
                        item = Path(parent) / name
                        if not item.is_symlink():
                            try:
                                total += item.stat().st_size
                            except OSError:
                                continue
                        seen += 1
                        if seen > 20000:
                            return total
            return total
        except OSError:
            return -1

    notice("Private Android build launched (T+0m)")
    with path.open("wb", buffering=0) as writer:
        proc = subprocess.Popen(command, stdout=writer, stderr=subprocess.STDOUT, start_new_session=True)
        def on_signal(signum, frame):
            stop.set()
            terminate_group(proc)
        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)

        def heartbeat():
            previous_size = 0
            previous_free_gib = None
            previous_hub_bytes = None
            while not stop.wait(args.heartbeat):
                now = time.monotonic()
                try:
                    size = path.stat().st_size
                    free_gib = shutil.disk_usage(os.environ.get("RUNNER_TEMP", str(path.parent))).free / (1024 ** 3)
                except OSError:
                    size, free_gib = previous_size, -1
                active = size > previous_size
                if active:
                    state["log_time"] = now
                previous_size = size
                hub_bytes = hub_temp_bytes()
                hub_growth = (max(0, hub_bytes - previous_hub_bytes)
                              if hub_bytes >= 0 and previous_hub_bytes is not None and previous_hub_bytes >= 0
                              else 0)
                previous_hub_bytes = hub_bytes
                # A large reduction in free space is a coarse installation
                # progress hint, not proof that Unity itself is writing.
                disk_drop = (max(0.0, previous_free_gib - free_gib)
                             if previous_free_gib is not None and free_gib >= 0 else 0.0)
                previous_free_gib = free_gib if free_gib >= 0 else previous_free_gib
                disk_activity = disk_drop >= 0.05
                if active or hub_growth >= 1024 * 1024 or disk_activity:
                    state["progress_time"] = now
                editor_count, hub_count, gameci_count = process_counts()
                info = {
                    "time_utc": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": int(now - start),
                    "last_phase": state["phase"],
                    "phase_age_seconds": int(now - state["phase_time"]),
                    "last_log_activity_seconds": int(now - state["log_time"]),
                    "last_observed_activity_seconds": int(now - state["progress_time"]),
                    "log_bytes": size,
                    "hub_temp_bytes": hub_bytes,
                    "hub_temp_growth_bytes": hub_growth,
                    "disk_drop_gib": round(disk_drop, 3),
                    "editor_named_processes": editor_count,
                    "hub_named_processes": hub_count,
                    "gameci_named_processes": gameci_count,
                    "free_gib": round(free_gib, 2),
                }
                with health_path.open("a", encoding="utf-8") as health:
                    health.write(json.dumps(info, ensure_ascii=True) + "\n")
                disk = "low" if 0 <= free_gib < args.min_free_gib else "unknown" if free_gib < 0 else "ok"
                def presence(count):
                    return "seen" if count > 0 else "not-seen" if count == 0 else "unknown"
                notice("Heartbeat T+%dm; log=%s; installer-io=%s; editor=%s; hub=%s; disk=%s" % (
                    int((now - start) / 60), "growing" if active else "quiet",
                    "active" if hub_growth >= 1024 * 1024 or disk_activity else "quiet",
                    presence(editor_count), presence(hub_count), disk))
                reason = None
                if 0 <= free_gib < args.min_free_gib:
                    reason = "low disk space"
                elif args.max_no_output > 0 and now - state["progress_time"] >= args.max_no_output:
                    reason = "no observable build or installer activity within limit"
                elif args.max_no_phase > 0 and now - state["phase_time"] >= args.max_no_phase:
                    reason = "no recognized build phase within limit"
                if reason and proc.poll() is None:
                    timeout_reason.append(reason)
                    notice("Watchdog stopping build: " + reason + "; sealed diagnostics will be retained")
                    terminate_group(proc)
                    return

        watcher = threading.Thread(target=heartbeat, name="simple-health", daemon=True)
        watcher.start()
        pending = b""
        with path.open("rb", buffering=0) as reader:
            while True:
                chunk = reader.read(65536)
                if chunk:
                    state["log_time"] = time.monotonic()
                    state["progress_time"] = state["log_time"]
                    pending += chunk
                    *lines, pending = pending.split(b"\n")
                    for line in lines:
                        report(line)
                    if len(pending) > 131072:
                        report(pending)
                        pending = pending[-4096:]
                    continue
                if proc.poll() is not None:
                    if pending:
                        report(pending)
                    break
                time.sleep(0.3)
        code = proc.wait()
        stop.set()
        watcher.join(timeout=6)

    if timeout_reason:
        print("::error title=Simple CI watchdog::Build stopped: " + timeout_reason[0] + ". Inspect encrypted diagnostics.", flush=True)
        return 124
    if "Addressables" in failures:
        print("::error title=Simple CI Addressables::Addressables content build failed; rejecting build.", flush=True)
        return 86
    if code == 0:
        notice("Build command completed successfully")
    else:
        labels = ", ".join(label for label, _ in FAILURE_MARKERS if label in failures) or "Unclassified failure"
        print("::error title=Simple CI build::Build failed (" + labels + "); inspect encrypted diagnostics.", flush=True)
    return code if code >= 0 else 128 + abs(code)


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        print("::error title=Simple CI monitor::Monitor failed; inspect encrypted diagnostics.", flush=True)
        sys.exit(125)
