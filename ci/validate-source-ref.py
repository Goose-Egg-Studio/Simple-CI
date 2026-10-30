#!/usr/bin/env python3
"""Validate a user-selected Unity source ref before minting an App token.

Never echo the ref into public Actions logs: even reference names may be
sensitive within a private source repository.
"""
import argparse
import re
import sys

REF_PARTS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")


def valid_ref(value):
    if SHA40.fullmatch(value):
        return True
    if not REF_PARTS.fullmatch(value):
        return False
    if value == "HEAD" or value.startswith(("refs/", "remotes/", "/")):
        # Do not allow arbitrary remote-tracking or symbolic git refs.
        return False
    if value.endswith(("/", ".")) or "//" in value or ".." in value:
        return False
    if any(segment in (".", "..") or segment.endswith(".lock")
           for segment in value.split("/")):
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()
    if not valid_ref(args.ref):
        print("Simple CI: invalid source ref format; use a branch, tag or full commit SHA.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
