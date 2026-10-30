#!/usr/bin/env bash
# GameCI v0.1.48 hardcodes /Applications/Unity/Hub/Editor/<version>.
# Prepare the compatibility symlink *before* downloading the Unity Editor,
# so an unwritable/occupied system path cannot waste a full installation.
set -Eeuo pipefail
umask 077

: "${SIMPLE_CI_LOG_DIR:?private diagnostic directory required}"
: "${SIMPLE_CI_LINK_ROOT:?GameCI root required}"
: "${SIMPLE_CI_LINK_VERSION:?Unity Editor version required}"
: "${SIMPLE_CI_LINK_TARGET:?user-owned Editor directory required}"

mkdir -p "$SIMPLE_CI_LOG_DIR"
LOG="$SIMPLE_CI_LOG_DIR/gameci-path-preflight-errors.log"
REPORT="$SIMPLE_CI_LOG_DIR/gameci-path-preflight.txt"
ROOT="$SIMPLE_CI_LINK_ROOT"
VERSION="$SIMPLE_CI_LINK_VERSION"
TARGET="$SIMPLE_CI_LINK_TARGET"
VERSION_PATH="$ROOT/$VERSION"

# Don't allow arbitrary names or accidental path substitution.
if [[ ! "$VERSION" =~ ^[0-9]{4}\.[0-9]+\.[0-9]+[abfp][0-9]+$ ]] ||
   [[ "$TARGET" != /* || "$ROOT" != /* ]]; then
  echo "invalid-input" > "$REPORT"
  exit 40
fi

fail() {
  local kind="$1" status="$2"
  printf 'result=%s\n' "$kind" >> "$REPORT"
  printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_failure'
  case "$kind" in
    root-symlink|version-occupied|unrecognized-link)
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_conflict' ;;
    *)
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_permission' ;;
  esac
  echo "GameCI compatibility directory preflight failed; inspect sealed diagnostics." >&2
  exit "$status"
}

# Log no untrusted paths publicly; the private report contains only statuses.
printf 'preflight=started\n' > "$REPORT"
if [[ -L "$ROOT" ]]; then
  fail root-symlink 52
fi
if [[ -e "$ROOT" && ! -d "$ROOT" ]]; then
  fail root-not-directory 53
fi

# Hosted macOS runners may need passwordless sudo to create /Applications
# subdirectories. Try user permissions first, then sudo -n (never prompt).
if ! mkdir -p "$ROOT" >> "$LOG" 2>&1; then
  if ! sudo -n mkdir -p "$ROOT" >> "$LOG" 2>&1; then
    fail root-unwritable 54
  fi
fi

if [[ -L "$VERSION_PATH" ]]; then
  if [[ "$(readlink "$VERSION_PATH")" != "$TARGET" ]]; then
    fail unrecognized-link 55
  fi
elif [[ -e "$VERSION_PATH" ]]; then
  # An empty version directory is safe to replace. Never delete files,
  # overwrite a preinstalled Editor or recursively remove any directory.
  if [[ ! -d "$VERSION_PATH" ]]; then
    fail version-occupied 56
  fi
  if ! rmdir "$VERSION_PATH" >> "$LOG" 2>&1; then
    if ! sudo -n rmdir "$VERSION_PATH" >> "$LOG" 2>&1; then
      fail version-occupied 57
    fi
  fi
fi

if [[ ! -L "$VERSION_PATH" ]]; then
  if ! ln -s "$TARGET" "$VERSION_PATH" >> "$LOG" 2>&1; then
    if ! sudo -n ln -s "$TARGET" "$VERSION_PATH" >> "$LOG" 2>&1; then
      fail link-unwritable 58
    fi
  fi
fi

[[ -L "$VERSION_PATH" ]] || fail link-not-created 59
[[ "$(readlink "$VERSION_PATH")" == "$TARGET" ]] || fail link-target-mismatch 60
printf 'result=prepared\nroot=present\nversion-symlink=verified\n' >> "$REPORT"
