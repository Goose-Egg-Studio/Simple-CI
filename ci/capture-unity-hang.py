#!/usr/bin/env python3
"""Private-only snapshot for a silent macOS Unity Editor build.

The output directory is under RUNNER_TEMP/simple-private-logs and must be
uploaded ONLY after age encryption. Do not print ps output or Editor.log.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import unity_health

MAX_EDITOR_LOG_TAIL = 1024 * 1024
MAX_WORKER_LOG_TAIL = 256 * 1024


def append_log_tail(source, destination, size):
    if not source.is_file() or source.is_symlink():
        return False
    try:
        with source.open("rb") as reader:
            reader.seek(0, os.SEEK_END)
            reader.seek(max(0, reader.tell() - size))
            with destination.open("wb") as writer:
                writer.write(reader.read(size))
        destination.chmod(0o600)
        return True
    except OSError:
        return False


def capture(out_dir, tag, process_group):
    if not re.fullmatch(r"[a-z0-9-]{1,24}", tag):
        raise ValueError("invalid snapshot name")
    private_root = Path(os.environ["RUNNER_TEMP"]).resolve() / "simple-private-logs"
    output_root = Path(out_dir).resolve()
    if output_root != private_root:
        raise ValueError("snapshot output must be the private logs directory")
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = private_root / ("unity-hang-" + tag)
    destination.mkdir(mode=0o700, exist_ok=True)

    info = unity_health.processes_for_group(process_group)
    summary = {
        "unix_time": int(time.time()),
        "build_process_count": info["process_count"],
        "unity_editor_process_count": len(info["editor_pids"]),
        "asset_worker_process_count": info["worker_count"],
        "unity_cli_process_count": info["cli_count"],
        "cpu_time_seconds_by_pid": info["cpu_by_pid"],
        "editor_log_files_copied": 0,
        "sample_status": "not-run",
    }
    # Read executable names only, not argv/env. This may still contain paths,
    # so the listing is private and encrypted.
    try:
        raw = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pgid=,stat=,time=,comm="],
            capture_output=True, timeout=7, check=False,
        )
        (destination / "processes.txt").write_bytes(raw.stdout[:512 * 1024])
    except (OSError, subprocess.SubprocessError):
        pass

    for index, source in enumerate(unity_health.unity_log_files()[:12]):
        max_tail = MAX_EDITOR_LOG_TAIL if source.name.lower() == "editor.log" else MAX_WORKER_LOG_TAIL
        if append_log_tail(source, destination / ("unity-log-%02d.tail" % index), max_tail):
            summary["editor_log_files_copied"] += 1

    # When the last public stage is C# compilation or Asset Import, licensing
    # and Package Manager might still be the actual blocker. Preserve a short
    # tail of their well-known logs ONLY inside the age-encrypted archive.
    auxiliary = (
        "upm.log", "Unity.Licensing.Client.log",
        "Unity.Entitlements.Audit.log",
    )
    summary["auxiliary_log_files_copied"] = 0
    folders = [Path.home() / "Library" / "Logs" / "Unity",
               Path.home() / ".config" / "unity3d" / "Unity"]
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        folders.append(Path(workspace) / "project" / "Logs")
    for folder in folders:
        if folder.is_symlink() or not folder.is_dir():
            continue
        for name in auxiliary:
            if append_log_tail(folder / name,
                               destination / ("aux-log-%02d.tail" %
                                              summary["auxiliary_log_files_copied"]),
                               MAX_WORKER_LOG_TAIL):
                summary["auxiliary_log_files_copied"] += 1

    if sys.platform == "darwin" and info["editor_pids"]:
        # A 4-second macOS sample can reveal a licensing wait, import lock,
        # asset worker deadlock or blocked Unity thread. This output may
        # contain private source paths: retain ONLY inside the age archive.
        pid = info["editor_pids"][0]
        sample_path = destination / "unity-editor.sample.txt"
        error_path = destination / "sample-error.txt"
        try:
            with error_path.open("wb") as errors:
                run = subprocess.run(
                    ["sample", str(pid), "4", "-file", str(sample_path)],
                    stdout=subprocess.DEVNULL, stderr=errors,
                    timeout=12, check=False,
                )
            summary["sample_status"] = "captured" if run.returncode == 0 else "failed"
            if sample_path.is_file() and sample_path.stat().st_size > 4 * 1024 * 1024:
                append_log_tail(sample_path, destination / "unity-editor.sample.tail", 4 * 1024 * 1024)
                sample_path.unlink()
            elif sample_path.is_file():
                sample_path.chmod(0o600)
        except (OSError, subprocess.SubprocessError):
            summary["sample_status"] = "unavailable"
    (destination / "snapshot.json").write_text(
        json.dumps(summary, sort_keys=True) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--pgid", type=int, required=True)
    args = parser.parse_args()
    try:
        capture(args.dir, args.tag, args.pgid)
    except (OSError, ValueError):
        # The caller redirects stdout and stderr into the private log tree.
        print("Unity hang snapshot unavailable.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
