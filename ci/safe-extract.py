#!/usr/bin/env python3
"""Extract decrypted Simple-CI implementation archives without path escapes.

An age public-key ciphertext does not authenticate who created it. Validate
all members before extracting to the runner's ephemeral private directory.
"""
import argparse
import os
import shutil
import sys
import tarfile
from pathlib import Path

MAX_FILES = 5000
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024


def safe_parts(name):
    if not name or name.startswith("/") or "\x00" in name:
        raise ValueError("invalid tar member name")
    pieces = [part for part in name.split("/") if part not in ("", ".")]
    if ".." in pieces or not pieces:
        raise ValueError("tar member escapes destination")
    return tuple(pieces)


def extract(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.is_symlink():
        raise ValueError("destination must not be a symlink")
    root = destination.resolve(strict=True)
    with tarfile.open(archive, "r:gz") as source:
        entries = []
        seen = set()
        total = 0
        for member in source:
            if member.isdir() and member.name.strip("./") == "":
                continue
            parts = safe_parts(member.name)
            if parts in seen:
                raise ValueError("duplicate tar member")
            seen.add(parts)
            if not (member.isdir() or member.isfile()):
                raise ValueError("tar links and special files are forbidden")
            if member.isfile():
                if not 0 <= member.size <= MAX_FILE_BYTES:
                    raise ValueError("tar file exceeds per-file limit")
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("tar archive exceeds size limit")
            entries.append((member, parts))
            if len(entries) > MAX_FILES:
                raise ValueError("tar archive exceeds file-count limit")

        # Reject an unsafe archive before creating any of its members.
        for member, parts in entries:
            target = root.joinpath(*parts)
            if target.is_symlink() or not target.parent.resolve().is_relative_to(root):
                raise ValueError("tar destination contains an unsafe symlink")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                if not target.is_dir() or target.is_symlink():
                    raise ValueError("tar directory collides with an existing file")
                target.chmod(0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not target.parent.resolve().is_relative_to(root):
                raise ValueError("tar parent escapes destination")
            if target.exists() and not target.is_file():
                raise ValueError("tar target collides with an existing directory")
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError("tar regular file has no content")
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(target, flags, 0o600)
            with os.fdopen(fd, "wb") as writer, stream:
                shutil.copyfileobj(stream, writer, length=1024 * 1024)
            target.chmod(0o700 if member.mode & 0o111 else 0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    try:
        extract(args.archive, args.destination)
    except (OSError, ValueError, tarfile.TarError):
        # The caller redirects stderr into its age-sealed private diagnostics.
        print("Simple CI: private archive failed safe extraction checks", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
