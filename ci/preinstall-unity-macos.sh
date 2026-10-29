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
EDITOR_DIR="$WRITABLE_ROOT/$VERSION"
CLI_HOME="$RUNNER_TEMP/simple-unity-cli"
# Keep CLI runtime data in the same per-job directory as its executable.
export UNITY_CLI_HOME="$CLI_HOME"
CLI="$CLI_HOME/bin/unity"
LOCAL_EDITOR="$EDITOR_DIR/Unity.app/Contents/MacOS/Unity"
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

# Unity CLI 1.0.0-beta.14+ supports self-contained installs using
# --download-directory. Do not write global Hub install-path configuration.
# Do not modify /Applications until the Editor and modules are verified.
# In particular, avoid install-path --set/--get and replacing the entire
# /Applications/Unity/Hub/Editor tree.
# Keep private copies of the options of the CLI actually installed today.
"$CLI" install --help > "$SIMPLE_CI_LOG_DIR/unity-cli-install-help.txt" 2>&1 || true
"$CLI" install-modules --help > "$SIMPLE_CI_LOG_DIR/unity-cli-modules-help.txt" 2>&1 || true
if ! grep -Fq -- '--download-directory' "$SIMPLE_CI_LOG_DIR/unity-cli-install-help.txt" ||
   ! grep -Fq -- '--download-directory' "$SIMPLE_CI_LOG_DIR/unity-cli-modules-help.txt"; then
  printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_download_directory_unsupported'
  echo 'Installed Unity CLI lacks the documented self-contained install flag.' >&2
  exit 49
fi

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

# A pre-created parent is writable, but the Editor payload directory is
# created by the self-contained installer itself.
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_start'
run_cli_stage editor install "$VERSION" \
  --changeset "$CHANGESET" --architecture x86_64 \
  --download-directory "$EDITOR_DIR" \
  --yes --accept-eula
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_done'
test -x "$LOCAL_EDITOR" || {
  printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_path_invalid'
  echo 'Editor binary missing from self-contained download directory.' >&2
  exit 32
}

printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_modules_start'
run_cli_stage modules install-modules \
  --download-directory "$EDITOR_DIR" \
  --module android --child-modules --accept-eula
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_modules_done'

LOCAL_ANDROID="$EDITOR_DIR/Unity.app/Contents/PlaybackEngines/AndroidPlayer"
test -d "$LOCAL_ANDROID" || { echo 'Android Build Support missing'; exit 33; }
test -d "$LOCAL_ANDROID/SDK" || { echo 'Unity-bundled Android SDK missing'; exit 34; }
test -d "$LOCAL_ANDROID/NDK" || { echo 'Unity-bundled Android NDK missing'; exit 35; }
test -d "$LOCAL_ANDROID/OpenJDK" || { echo 'Unity-bundled Android OpenJDK missing'; exit 36; }

# GameCI v0.1.48 requires the legacy /Applications path. Link ONLY this
# pinned version; never replace/remove the root or unrelated installations.
# All actual Editor files stay in the runner-owned self-contained directory.
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_start'
sudo -n mkdir -p "$STANDARD_ROOT"
STANDARD_VERSION="$STANDARD_ROOT/$VERSION"
if [[ -L "$STANDARD_VERSION" ]]; then
  if [[ "$(readlink "$STANDARD_VERSION")" != "$EDITOR_DIR" ]]; then
    printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_failure'
    echo 'Unrecognized existing GameCI Editor symlink; refusing replacement.' >&2
    exit 46
  fi
elif [[ -e "$STANDARD_VERSION" ]]; then
  printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_failure'
  echo 'Existing real Editor version directory; refusing to overwrite.' >&2
  exit 47
else
  if ! sudo -n ln -s "$EDITOR_DIR" "$STANDARD_VERSION"; then
    printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_failure'
    echo 'Unable to create the GameCI compatibility version symlink.' >&2
    exit 48
  fi
fi
test -x "$EDITOR" || {
  printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_failure'
  echo 'GameCI cannot resolve the Editor through its required standard path.' >&2
  exit 50
}
test -d "$ANDROID/SDK" && test -d "$ANDROID/NDK" &&
  test -d "$ANDROID/OpenJDK" || {
    printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_failure'
    echo 'GameCI cannot resolve Android dependencies through its standard path.' >&2
    exit 51
  }
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_path_done'

{
  printf 'Installer=official standalone Unity CLI beta channel\n'
  printf 'Editor version=%s\n' "$VERSION"
  printf 'Changeset=%s\n' "$CHANGESET"
  printf 'CLI version=%s\n' "$CLI_VERSION"
  printf 'Self-contained install=verified\n'
  printf 'GameCI symlink=verified\n'
  for component in "$ANDROID/SDK" "$ANDROID/NDK" "$ANDROID/OpenJDK"; do
    if [[ -d "$component" ]]; then printf 'Android component present\n'; fi
  done
} > "$SIMPLE_CI_LOG_DIR/unity-cli-preinstall-status.txt"
printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_validated'
