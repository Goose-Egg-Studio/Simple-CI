#!/usr/bin/env python3
"""Capture Unity Hub installation diagnostics inside the private log directory.

Never print Hub logs or file paths to public Actions. The finalizer seals the
entire private log directory with the artifact age recipient before upload.
"""
import json
import os
from pathlib import Path


def main():
    old_umask = os.umask(0o077)
    try:
        destination = Path(os.environ["RUNNER_TEMP"]) / "simple-private-logs"
        destination.mkdir(parents=True, exist_ok=True)
        hub = Path.home() / "Library" / "Application Support" / "UnityHub" / "logs"
        version = "2022.3.62f3"
        editor_root = Path("/Applications/Unity/Hub/Editor") / version / "Unity.app" / "Contents"
        android_root = editor_root / "PlaybackEngines" / "AndroidPlayer"
        state = {
            "hub_app_exists": Path("/Applications/Unity Hub.app").is_dir(),
            "editor_binary_exists": (editor_root / "MacOS" / "Unity").is_file(),
            "android_player_exists": android_root.is_dir(),
            "bundled_sdk_exists": (android_root / "SDK").is_dir(),
            "bundled_ndk_exists": (android_root / "NDK").is_dir(),
            "bundled_openjdk_exists": (android_root / "OpenJDK").is_dir(),
            "hub_log_directory_exists": hub.is_dir(),
            "hub_log_files_saved": 0,
        }
        if hub.is_dir():
            files = []
            for item in hub.iterdir():
                if (item.is_file() and not item.is_symlink()
                        and item.suffix.lower() in (".json", ".log", ".txt")):
                    files.append(item)
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            saved = destination / "unity-hub"
            for index, source in enumerate(files[:8]):
                saved.mkdir(parents=True, exist_ok=True)
                # Keep only the most recent 4 MiB for each of at most 8 logs.
                # These can include private details, but are never uploaded raw.
                with source.open("rb") as reader:
                    size = source.stat().st_size
                    if size > 4 * 1024 * 1024:
                        reader.seek(-4 * 1024 * 1024, os.SEEK_END)
                    data = reader.read(4 * 1024 * 1024)
                (saved / ("hub-log-%02d.tail" % index)).write_bytes(data)
                state["hub_log_files_saved"] += 1
        (destination / "hub-install-state.json").write_text(
            json.dumps(state, indent=2) + "\n", encoding="utf-8")
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A best-effort finalizer should not lose all diagnostics because
        # Unity Hub's logs are absent, locked, or unexpectedly structured.
        print("Unity Hub diagnostic snapshot unavailable; continuing sealing.")
