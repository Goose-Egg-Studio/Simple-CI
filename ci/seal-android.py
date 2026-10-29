#!/usr/bin/env python3
"""Package Android APK, AAB and diagnostics as THREE independent age archives.

Never print raw paths, filenames or Unity output to the public GitHub Actions
console. Each artifact is encrypted before upload. A failed/missing APK or AAB
does not prevent upload of the encrypted diagnostics archive.
"""
import argparse
import gzip
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

MIB = 1024 * 1024


def collect_macos_diagnostics(log_dir):
    """Bound log sizes; copy only into the private directory."""
    home = Path.home()
    roots = [
        home / "Library" / "Application Support" / "UnityHub" / "logs",
        home / "Library" / "Logs" / "Unity",
        home / ".config" / "unity3d",
    ]
    collected = 0
    for index, root in enumerate(roots):
        if not root.is_dir():
            continue
        try:
            candidates = sorted(
                (f for f in root.rglob("*.log") if f.is_file() and not f.is_symlink()),
                key=lambda f: f.stat().st_mtime, reverse=True
            )[:8]
            for n, source in enumerate(candidates):
                target = log_dir / ("unity-install-{}-{}.log".format(index, n))
                with source.open("rb") as reader, target.open("wb") as writer:
                    reader.seek(max(0, source.stat().st_size - 4 * MIB))
                    shutil.copyfileobj(reader, writer)
                collected += 1
        except (OSError, ValueError):
            pass
    try:
        usage = shutil.disk_usage(str(log_dir))
        with (log_dir / "runner-snapshot.txt").open("w", encoding="utf-8") as f:
            f.write("disk_total_bytes={}\ndisk_free_bytes={}\n".format(usage.total, usage.free))
            f.write("unity_related_log_files={}\n".format(collected))
    except OSError:
        pass


def select_output(dist, extension):
    if not dist.is_dir():
        return None, "dist-missing"
    root = dist.resolve()
    files = []
    for f in dist.rglob("*"):
        if f.suffix.lower() != extension or not f.is_file() or f.is_symlink():
            continue
        try:
            if f.resolve().is_relative_to(root):
                files.append(f)
        except (OSError, ValueError):
            continue
    if len(files) != 1:
        return None, "missing" if not files else "ambiguous"
    return files[0], "found"


def seal(source, arcname, destination, recipient, compression=1):
    """Encrypt a streaming tar.gz directly; never write plaintext tar to disk."""
    temp = destination.with_suffix(destination.suffix + ".partial")
    try:
        if temp.exists():
            temp.unlink()
        with temp.open("wb") as cipher:
            proc = subprocess.Popen(
                ["age", "-r", recipient],
                stdin=subprocess.PIPE,
                stdout=cipher,
                stderr=sys.stderr
            )
            try:
                # Explicit gzip wrapper supports Python 3.11's streaming
                # tarfile API (which lacks a compresslevel parameter).
                with gzip.GzipFile(fileobj=proc.stdin, mode="wb", compresslevel=compression) as gz:
                    with tarfile.open(fileobj=gz, mode="w|") as tar:
                        tar.add(str(source), arcname=arcname, recursive=True)
                proc.stdin.close()
                rc = proc.wait(timeout=60)
                if rc:
                    raise RuntimeError("age-exit-code")
            except Exception:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
                proc.kill() if proc.poll() is None else None
                proc.wait()
                raise
        if temp.stat().st_size == 0:
            raise RuntimeError("empty-age-file")
        temp.replace(destination)
        return True
    except Exception as exc:
        # Caller redirects stderr to a private file; never expose this on
        # public Actions stdout because exceptions may contain private paths.
        print("seal-error={} {}".format(type(exc).__name__, str(exc)), file=sys.stderr)
        temp.unlink(missing_ok=True)
        return False


def write_outputs(apk, aab, logs):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write("has_apk={}\nhas_aab={}\nhas_logs={}\n".format(
            str(apk).lower(), str(aab).lower(), str(logs).lower()
        ))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--logs", required=True)
    p.add_argument("--dist", required=True)
    p.add_argument("--recipient-file", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--run-id", required=True)
    args = p.parse_args()
    log_dir = Path(args.logs)
    log_dir.mkdir(parents=True, exist_ok=True)
    dist = Path(args.dist)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    recipient = Path(args.recipient_file).read_text(encoding="utf-8").strip()
    if not recipient.startswith("age1") or "\n" in recipient:
        raise ValueError("invalid public age recipient")

    collect_macos_diagnostics(log_dir)
    apk, apk_status = select_output(dist, ".apk")
    aab, aab_status = select_output(dist, ".aab")
    summary = log_dir / "artifact-packaging-status.txt"
    summary.write_text(
        "apk={}\naab={}\n".format(apk_status, aab_status),
        encoding="utf-8"
    )

    prefix = "android-" + args.run_id
    logs_target = out / (prefix + "-logs.tar.gz.age")
    apk_target = out / (prefix + "-apk.tar.gz.age")
    aab_target = out / (prefix + "-aab.tar.gz.age")
    # Encrypt diagnostics first so disk pressure during large APK/AAB
    # encryption cannot prevent collecting the investigation material.
    has_logs = seal(log_dir, "private-logs", logs_target, recipient, compression=6)
    has_apk = bool(apk) and seal(
        apk, "build-outputs/" + apk.name, apk_target, recipient
    )
    has_aab = bool(aab) and seal(
        aab, "build-outputs/" + aab.name, aab_target, recipient
    )

    with summary.open("a", encoding="utf-8") as f:
        f.write("apk_sealed={}\naab_sealed={}\nlogs_sealed={}\n".format(
            has_apk, has_aab, has_logs
        ))
    # Update the encrypted logs with final packaging results; never upload
    # the unencrypted status file. Failure here leaves the original log
    # archive in place as a fallback.
    if has_logs:
        updated_target = out / (prefix + "-logs-updated.tar.gz.age")
        if seal(log_dir, "private-logs", updated_target, recipient, compression=6):
            updated_target.replace(logs_target)
    write_outputs(has_apk, has_aab, has_logs)
    if has_logs:
        print("Independent encrypted diagnostic archive prepared.")
    if has_apk:
        print("Independent encrypted APK archive prepared.")
    if has_aab:
        print("Independent encrypted AAB archive prepared.")
    return 0 if has_logs else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Outer workflow redirects stdout and stderr to an encrypted log.
        print("Android sealing helper failed.", file=sys.stderr)
        sys.exit(1)
