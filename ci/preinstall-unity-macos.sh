#!/usr/bin/env bash
# Install the precise macOS Intel Unity Editor and all Android dependencies
# using the standalone Unity CLI, before invoking the sealed GameCI build.
# The parent safe-progress monitor captures ALL output into a private file.
set -Eeuo pipefail
umask 077
# Diagnostic line and exit status stay inside the separately age-encrypted logs.
trap 'status=$?; printf "Unity installer shell failed at line %s (exit %s)\\n" "$LINENO" "$status" >&2' ERR

: "${SIMPLE_CI_LOG_DIR:?private logging directory required}"
mkdir -p "$SIMPLE_CI_LOG_DIR"

VERSION="2022.3.62f3"
CHANGESET="96770f904ca7"
INSTALL_ROOT="/Applications/Unity/Hub/Editor"
EDITOR="$INSTALL_ROOT/$VERSION/Unity.app/Contents/MacOS/Unity"
ANDROID="$INSTALL_ROOT/$VERSION/Unity.app/Contents/PlaybackEngines/AndroidPlayer"

printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_bootstrap_start'
if ! brew list --cask --versions unity-cli >/dev/null 2>&1; then
  brew install --cask unity-cli
fi
command -v unity >/dev/null
unity --version
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_bootstrap_done'

# The previous runner exited before the Editor install marker, inside
# this path preparation block. Do not make a non-essential path setter a
# fatal prerequisite: the final component gate below remains fail-closed.
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_start'
if sudo -n mkdir -p "$INSTALL_ROOT" && sudo -n chown "$(id -u):$(id -g)" "$INSTALL_ROOT"; then
  echo 'Unity Editor installation directory prepared.'
else
  echo 'Unable to prepare standard Editor directory; CLI installation will still be attempted.'
fi
if unity install-path --set "$INSTALL_ROOT"; then
  echo 'Unity CLI Editor path configured.'
elif unity editors install-path --set "$INSTALL_ROOT"; then
  echo 'Unity CLI Editor path configured using editors subcommand.'
else
  echo 'Unity CLI path configuration failed; proceeding to install and verifying final location.'
fi
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_done'

# Snapshot the exact command flags supported by the installed beta.
# Detailed help/diagnostics are private and are age-sealed by the finalizer.
unity install --help > "$SIMPLE_CI_LOG_DIR/unity-cli-install-help.txt" 2>&1 || true
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_start'

# The install starts without Unity Hub --headless. Separate Editor and
# Android module operations to isolate usage errors instead of repeatedly
# changing a six-flag invocation without concrete CLI diagnostic evidence.
CLI="$(command -v unity)"

run_cli_stage() {
  local stage="$1"
  shift
  local detail="$SIMPLE_CI_LOG_DIR/unity-cli-${stage}-detail.log"
  local result=0
  printf 'Unity CLI stage=%s\n' "$stage"
  set +e
  "$CLI" "$@" > "$detail" 2>&1
  result=$?
  set -e

  if (( result != 0 )); then
    # Only retry a real authorization/elevation error. An argument usage
    # error (code 2) must never be hidden by another invocation.
    if grep -Eiq 'ELEVATION_FAILED|ELEVATION_CANCELLED|permission denied|administrator permission|administrator privileges|authorization failed' "$detail"; then
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_elevation_retry'
      if sudo -n true; then
        set +e
        sudo -n -H "$CLI" "$@" > "$SIMPLE_CI_LOG_DIR/unity-cli-${stage}-root-retry.log" 2>&1
        result=$?
        set -e
        detail="$SIMPLE_CI_LOG_DIR/unity-cli-${stage}-root-retry.log"
      else
        printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_elevation_unavailable'
      fi
    fi
  fi

  if (( result != 0 )); then
    # Only publish a fixed category, never arbitrary CLI output, paths,
    # machine/environment details, or Unity licensing information.
    if (( result == 2 )) || grep -Eiq 'INVALID_COMMAND_ARGS|unknown option|unexpected argument|unrecognized option|unknown flag' "$detail"; then
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_invalid_arguments'
    elif grep -Eiq 'RELEASE_NOT_FOUND|VERSION_NOT_FOUND|EDITOR_NOT_FOUND|No matching editor|unable to resolve.*changeset' "$detail"; then
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_release_unavailable'
    elif grep -Eiq 'ELEVATION_FAILED|ELEVATION_CANCELLED|permission denied|administrator permission|administrator privileges|authorization failed' "$detail"; then
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_elevation_failure'
    else
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_install_failed'
    fi
    printf 'Unity CLI stage %s failed with exit status %d; see encrypted diagnostics.\n' "$stage" "$result" >&2
    return "$result"
  fi
}

# First, install only the core Editor. This is the smallest documented
# unattended invocation retaining the exact project's pinned changeset.
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_start'
run_cli_stage editor install "$VERSION" \
  --changeset "$CHANGESET" \
  --yes --accept-eula
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_done'

if ! test -x "$EDITOR"; then
  printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_path_invalid'
  echo 'Unity Editor binary missing at GameCI expected path after install.' >&2
  exit 32
fi

# Then install Android Build Support and its bundled SDK, NDK, OpenJDK.
# Isolating this stage reveals incompatibility with old 2022.3 module IDs,
# without retrying an already successful Editor download.
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_modules_start'
run_cli_stage modules install-modules \
  --editor-version "$VERSION" \
  --module android --child-modules --accept-eula
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_modules_done'

# Fail closed: an incomplete install must never invoke the GameCI builder.
test -d "$ANDROID" || { echo 'Android Build Support missing after Unity CLI install'; exit 33; }
test -d "$ANDROID/SDK" || { echo 'Unity-bundled Android SDK missing'; exit 34; }
test -d "$ANDROID/NDK" || { echo 'Unity-bundled Android NDK missing'; exit 35; }
test -d "$ANDROID/OpenJDK" || { echo 'Unity-bundled Android OpenJDK missing'; exit 36; }

# Private, non-secret state summary, enclosed in the encrypted logs archive.
{
  printf 'Installer=standalone Unity CLI\n'
  printf 'Editor version=%s\n' "$VERSION"
  printf 'Changeset=%s\n' "$CHANGESET"
  for folder in "$ANDROID/SDK" "$ANDROID/NDK" "$ANDROID/OpenJDK"; do
    if [ -d "$folder" ]; then printf 'Android component present\n'; fi
  done
} > "$SIMPLE_CI_LOG_DIR/unity-cli-preinstall-status.txt"
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_validated'
