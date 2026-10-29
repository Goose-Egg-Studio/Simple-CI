#!/usr/bin/env bash
# Bootstrap Unity's current standalone CLI. Install Editor into a runner-owned
# directory and expose it at the path required by pinned GameCI v0.1.48.
# All installer output is captured by safe-progress.py, then age-encrypted.
set -Eeuo pipefail
umask 077
trap 'status=$?; printf "Unity installer shell failed at line %s (exit %s)\n" "$LINENO" "$status" >&2' ERR

: "${SIMPLE_CI_LOG_DIR:?private logging directory required}"
: "${RUNNER_TEMP:?GitHub runner temporary directory required}"
mkdir -p "$SIMPLE_CI_LOG_DIR"

VERSION="2022.3.62f3"
CHANGESET="96770f904ca7"
STANDARD_ROOT="/Applications/Unity/Hub/Editor"
# Do not ask a headless installer to write directly under /Applications.
# All Editor payloads remain on the same runner disk, and are ephemeral.
WRITABLE_ROOT="$RUNNER_TEMP/simple-unity-editors"
CLI_HOME="$RUNNER_TEMP/simple-unity-cli"
# Keep CLI runtime data in the same per-job directory as its executable.
export UNITY_CLI_HOME="$CLI_HOME"
CLI="$CLI_HOME/bin/unity"
EDITOR="$STANDARD_ROOT/$VERSION/Unity.app/Contents/MacOS/Unity"
ANDROID="$STANDARD_ROOT/$VERSION/Unity.app/Contents/PlaybackEngines/AndroidPlayer"

printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_bootstrap_start'
mkdir -p "$CLI_HOME" "$WRITABLE_ROOT"
chmod 700 "$CLI_HOME" "$WRITABLE_ROOT"
# Homebrew's unity-cli cask previously supplied 1.0.0-beta.6, which produced
# permission errors on this runner. Follow Unity's official, maintained
# beta-channel installer instead of relying on the cask's version.
INSTALLER="$RUNNER_TEMP/simple-unity-cli-install.sh"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  https://unity.com/install.sh --output "$INSTALLER"
UNITY_CLI_CHANNEL=beta UNITY_CLI_HOME="$CLI_HOME" bash "$INSTALLER"
test -x "$CLI" || {
  echo 'Official Unity CLI installer did not put a binary under UNITY_CLI_HOME/bin.' >&2
  exit 41
}
CLI_VERSION="$("$CLI" --version)"
printf '%s\n' "$CLI_VERSION"
# Fail closed if the upstream installer unexpectedly returns the known-broken
# old beta instead of a newer beta release.
if [[ "$CLI_VERSION" =~ ^1\.0\.0-beta\.([0-9]+)$ ]] && (( BASH_REMATCH[1] < 14 )); then
  echo 'Standalone CLI version is older than the minimum tested release family.' >&2
  exit 42
fi
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_bootstrap_done'

printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_start'
# The CLI and Hub share the selected install path in user configuration.
# Target must exist and be writable BEFORE calling install-path --set.
touch "$WRITABLE_ROOT/.simple-ci-write-check"
rm -f "$WRITABLE_ROOT/.simple-ci-write-check"
if "$CLI" install-path --set "$WRITABLE_ROOT" \
    > "$SIMPLE_CI_LOG_DIR/unity-cli-install-path.log" 2>&1; then
  :
elif "$CLI" editors install-path --set "$WRITABLE_ROOT" \
    >> "$SIMPLE_CI_LOG_DIR/unity-cli-install-path.log" 2>&1; then
  :
else
  echo 'Unity CLI could not set the writable Editor installation directory; see encrypted logs.' >&2
  exit 43
fi
"$CLI" install-path --get > "$SIMPLE_CI_LOG_DIR/unity-cli-current-path.log" 2>&1 || {
  echo 'Unity CLI failed to read back the configured Editor installation directory.' >&2
  exit 44
}
grep -Fq -- "$WRITABLE_ROOT" "$SIMPLE_CI_LOG_DIR/unity-cli-current-path.log" || {
  echo 'Unity CLI did not retain the writable Editor installation directory.' >&2
  exit 45
}

# GameCI checks a hardcoded /Applications/Unity/Hub/Editor/... path.
# Make that standard path a symlink to the runner-owned install root.
# Do NOT chmod /Applications, remove existing installs, or follow preexisting
# unexpected symlinks. The hosted runner is expected to start fresh.
sudo -n mkdir -p "/Applications/Unity/Hub"
if [[ -L "$STANDARD_ROOT" ]]; then
  [[ "$(readlink "$STANDARD_ROOT")" == "$WRITABLE_ROOT" ]] || {
    echo 'Unexpected existing Unity Editor symlink at GameCI standard path.' >&2
    exit 46
  }
elif [[ -e "$STANDARD_ROOT" ]]; then
  # A fresh runner can have an empty Editor directory. Never remove a
  # directory containing installations or other user data.
  sudo -n rmdir "$STANDARD_ROOT" || {
    echo 'Existing nonempty Unity Editor directory cannot be replaced safely.' >&2
    exit 47
  }
  sudo -n ln -s "$WRITABLE_ROOT" "$STANDARD_ROOT"
else
  sudo -n ln -s "$WRITABLE_ROOT" "$STANDARD_ROOT"
fi
test -w "$STANDARD_ROOT" || {
  echo 'Editor standard path does not resolve to a writable directory.' >&2
  exit 48
}
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_done'

# Keep private copies of the options of the CLI actually installed today.
"$CLI" install --help > "$SIMPLE_CI_LOG_DIR/unity-cli-install-help.txt" 2>&1 || true
"$CLI" install-modules --help > "$SIMPLE_CI_LOG_DIR/unity-cli-modules-help.txt" 2>&1 || true

run_cli_stage() {
  local stage="$1"
  shift
  local detail="$SIMPLE_CI_LOG_DIR/unity-cli-${stage}-detail.log"
  local result=0
  printf 'Unity CLI stage=%s\n' "$stage"
  set +e
  "$CLI" "$@" 2>&1 | tee "$detail"
  result=${PIPESTATUS[0]}
  set -e
  if (( result != 0 )); then
    # Do not retry with sudo: that would switch HOME/configuration and may
    # silently install to the protected system default instead.
    if (( result == 2 )) || grep -Eiq 'INVALID_COMMAND_ARGS|unknown option|unexpected argument|unrecognized option|unknown flag' "$detail"; then
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_invalid_arguments'
    elif grep -Eiq 'RELEASE_NOT_FOUND|VERSION_NOT_FOUND|EDITOR_NOT_FOUND|No matching editor|unable to resolve.*changeset' "$detail"; then
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_release_unavailable'
    elif grep -Eiq 'ELEVATION_FAILED|ELEVATION_CANCELLED|permission denied|Access to (the )?path .* denied|access denied|administrator permission|administrator privileges|authorization failed|EACCES|EPERM' "$detail"; then
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_elevation_failure'
    else
      printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_install_failed'
    fi
    printf 'Unity CLI stage %s failed with exit status %d; inspect encrypted logs.\n' "$stage" "$result" >&2
    return "$result"
  fi
}

printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_start'
run_cli_stage editor install "$VERSION" \
  --changeset "$CHANGESET" --architecture x86_64 \
  --yes --accept-eula
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_done'

test -x "$EDITOR" || {
  printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_path_invalid'
  echo 'Unity Editor binary not found at the GameCI expected path.' >&2
  exit 32
}

printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_modules_start'
run_cli_stage modules install-modules \
  -e "$VERSION" -m android --child-modules --accept-eula
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_modules_done'

# Fail closed: missing Android components must never trigger the GameCI build.
test -d "$ANDROID" || { echo 'Android Build Support missing'; exit 33; }
test -d "$ANDROID/SDK" || { echo 'Unity-bundled Android SDK missing'; exit 34; }
test -d "$ANDROID/NDK" || { echo 'Unity-bundled Android NDK missing'; exit 35; }
test -d "$ANDROID/OpenJDK" || { echo 'Unity-bundled Android OpenJDK missing'; exit 36; }

{
  printf 'Installer=official standalone Unity CLI beta channel\n'
  printf 'Editor version=%s\n' "$VERSION"
  printf 'Changeset=%s\n' "$CHANGESET"
  printf 'CLI version=%s\n' "$CLI_VERSION"
  printf 'Path validation=passed\n'
  for component in "$ANDROID/SDK" "$ANDROID/NDK" "$ANDROID/OpenJDK"; do
    if [[ -d "$component" ]]; then printf 'Android component present\n'; fi
  done
} > "$SIMPLE_CI_LOG_DIR/unity-cli-preinstall-status.txt"
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_validated'
