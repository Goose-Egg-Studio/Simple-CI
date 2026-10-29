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
unity install --help > "$SIMPLE_CI_LOG_DIR/unity-cli-install-help.txt" 2>&1
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_start'

# The install starts without Unity Hub --headless. Unity CLI >= beta.9
# requests macOS administrator authorization *before* downloading; that
# request may fail immediately when there is no interactive desktop.
#
# First try unprivileged; retry as root ONLY for known elevation/permission
# failures. No retry for invalid options, missing releases or other errors.
# tee is safe here: safe-progress captures *all* stdout privately.
CLI="$(command -v unity)"
DETAIL="$SIMPLE_CI_LOG_DIR/unity-cli-install-detail.log"
INSTALL_ARGS=(install "$VERSION" --changeset "$CHANGESET"
  --module android --child-modules --architecture x86_64
  --non-interactive --yes --accept-eula --format ndjson)

set +e
"$CLI" "${INSTALL_ARGS[@]}" 2>&1 | tee "$DETAIL"
install_code=${PIPESTATUS[0]}
set -e

if (( install_code != 0 )); then
  if grep -Eiq 'ELEVATION_FAILED|ELEVATION_CANCELLED|permission denied|administrator permission|administrator privileges|authorization failed' "$DETAIL"; then
    printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_elevation_retry'
    # GitHub macOS hosted runners provide noninteractive sudo. Use the full
    # executable path; don't source login profiles or copy project secrets.
    if sudo -n true; then
      set +e
      sudo -n -H "$CLI" "${INSTALL_ARGS[@]}" 2>&1 | tee "$SIMPLE_CI_LOG_DIR/unity-cli-root-retry.log"
      install_code=${PIPESTATUS[0]}
      set -e
    else
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_elevation_unavailable'
    fi
  fi
fi

if (( install_code != 0 )); then
  if grep -Eiq 'INVALID_COMMAND_ARGS|unknown option|unexpected argument|unrecognized option|unknown flag' "$DETAIL"; then
    printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_invalid_arguments'
  elif grep -Eiq 'RELEASE_NOT_FOUND|VERSION_NOT_FOUND|EDITOR_NOT_FOUND|NOT_FOUND|No matching editor|unable to resolve.*changeset' "$DETAIL"; then
    printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_release_unavailable'
  elif grep -Eiq 'ELEVATION_FAILED|ELEVATION_CANCELLED|permission denied|administrator permission|administrator privileges|authorization failed' "$DETAIL"; then
    printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_elevation_failure'
  else
    printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_install_failed'
  fi
  printf 'Unity CLI install failed with exit status %d. Details remain in encrypted diagnostics.\n' "$install_code" >&2
  exit "$install_code"
fi
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_done'

# Fail closed: an incomplete install must never invoke the GameCI builder.
test -x "$EDITOR" || { echo 'Independent CLI install did not place Editor at GameCI expected path'; exit 32; }
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
