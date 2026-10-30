"""Quiet Unity-build health signals. Never expose private paths or command lines.

Pure helpers are also used by the fail-closed macOS diagnostics collector.
"""
import os
import re
import subprocess
from pathlib import Path

PS_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\S+)\s+(.*?)\s*$")
WORKER_NAMES = (
    "assetimportworker", "unityshadercompiler", "bee_backend",
    "il2cpp", "gradle", "java",
)


def cpu_seconds(value):
    """Parse BSD/macOS or Linux ps TIME (including optional days and fraction)."""
    try:
        day_count = 0
        if "-" in value:
            days, value = value.split("-", 1)
            day_count = int(days)
        items = value.split(":")
        if len(items) not in (2, 3):
            return None
        if len(items) == 2:
            hours, minutes, seconds = 0, int(items[0]), float(items[1])
        else:
            hours, minutes, seconds = int(items[0]), int(items[1]), float(items[2])
        if min(day_count, hours, minutes, seconds) < 0:
            return None
        return day_count * 86400 + hours * 3600 + minutes * 60 + seconds
    except (ValueError, TypeError):
        return None


def classify_command(command):
    """Labels are fixed, never a raw executable path."""
    lowered = command.lower()
    name = os.path.basename(lowered)
    if "/unity.app/contents/macos/unity" in lowered:
        return "editor"
    if name == "unity" and "/simple-unity-cli/" in lowered:
        return "cli"
    if any(token in lowered for token in WORKER_NAMES):
        return "worker"
    return "other"


def processes_for_group(pgid):
    """Return bounded numerical statistics, not ps argv with private arguments."""
    try:
        process = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,time=,comm="],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=True, timeout=6,
        )
    except (OSError, subprocess.SubprocessError):
        return {"cpu_by_pid": None, "editor_pids": [], "worker_count": -1,
                "process_count": -1, "cli_count": -1}
    tracked = {}
    editors = []
    workers = 0
    cli_count = 0
    process_count = 0
    for raw in process.stdout.splitlines():
        line = raw.decode("utf-8", "replace")
        match = PS_ROW.match(line)
        if not match:
            continue
        pid, group_id = int(match.group(1)), int(match.group(2))
        elapsed_cpu = cpu_seconds(match.group(3))
        kind = classify_command(match.group(4))
        if kind == "editor":
            editors.append(pid)
        elif kind == "worker":
            workers += 1
        elif kind == "cli":
            cli_count += 1
        if group_id == pgid or kind in ("editor", "worker"):
            process_count += 1
            if elapsed_cpu is not None:
                tracked[pid] = elapsed_cpu
    return {"cpu_by_pid": tracked, "editor_pids": editors,
            "worker_count": workers, "process_count": process_count,
            "cli_count": cli_count}


def cpu_delta(previous, current):
    """Total CPU seconds newly consumed by the observed build processes."""
    if previous is None or current is None:
        return None
    total = 0.0
    for pid, value in current.items():
        # New processes may have spent CPU time before the next heartbeat.
        baseline = previous.get(pid, 0.0)
        total += max(0.0, value - baseline)
    return total


def unity_log_files(home=None):
    base = Path(home) if home is not None else Path.home()
    roots = [base / "Library" / "Logs" / "Unity",
             base / ".config" / "unity3d"]
    # Unity 6 can keep a project-specific Editor.log; older versions
    # generally use the macOS global log. Observe both without reading
    # their text into Actions output.
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        roots.append(Path(workspace) / "project" / "Logs")
    found = []
    for folder in roots:
        try:
            if not folder.is_dir() or folder.is_symlink():
                continue
            for entry in folder.iterdir():
                name = entry.name.lower()
                if name == "editor.log" or (name.startswith("assetimportworker")
                                           and name.endswith(".log")):
                    if entry.is_file() and not entry.is_symlink():
                        found.append(entry)
                if len(found) >= 20:
                    return found
        except OSError:
            continue
    return found


def unity_log_stamps(home=None):
    """Stat only, no private log content leaves the runner."""
    stamps = {}
    for file in unity_log_files(home):
        try:
            st = file.stat()
            stamps[str(file)] = (st.st_size, st.st_mtime_ns)
        except OSError:
            continue
    return stamps


def log_changed(previous, current):
    if previous is None:
        return bool(current)
    return any(old != current.get(path) for path, old in previous.items()) or any(
        path not in previous for path in current
    )
