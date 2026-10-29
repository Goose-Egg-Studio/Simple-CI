#!/usr/bin/env bash
# Install the precise macOS Intel Unity Editor and all Android dependencies
# using the standalone Unity CLI, before invoking the sealed GameCI build.
# The parent safe-progress monitor captures ALL output into a private file.
set -euo pipefail
umask 077

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

# Canonical path expected by GameCI v0.1.48 SetupMac.
sudo mkdir -p "$INSTALL_ROOT"
sudo chown "$(id -u):$(id -g)" "$INSTALL_ROOT"
if unity install-path --help | grep -q -- '--set'; then
  unity install-path --set "$INSTALL_ROOT"
else
  echo 'Unity CLI install-path setting unavailable; verifying standard path after install.'
fi

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
