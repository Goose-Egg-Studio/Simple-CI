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

printf '%s\n' 'SIMPLE_CI_PHASE=unity_cli_editor_start'
# Intentionally bypass Unity Hub --headless. Do not emit raw CLI output to
# public Actions logs: safe-progress.py captures it to a private file.
unity install "$VERSION" \
  --changeset "$CHANGESET" \
  --module android \
  --child-modules \
  --architecture x86_64 \
  --non-interactive --yes --accept-eula
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
