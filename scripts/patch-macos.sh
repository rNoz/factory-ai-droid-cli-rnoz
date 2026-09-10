#!/usr/bin/env bash
# patch-macos.sh — Apply zero-waste titling patch to Factory CLI on macOS
#
# Usage:
#   ./patch-macos.sh                  # Auto-detects droid in PATH or standard dirs
#   ./patch-macos.sh /path/to/droid   # Patches a specific droid binary

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCHER="$SCRIPT_DIR/../patches/patch-droid.py"
KEYBINDING_PATCHER="$SCRIPT_DIR/../patches/patch_keybindings.py"

if [[ ! -f "$PATCHER" || ! -f "$KEYBINDING_PATCHER" ]]; then
  echo "Error: patch scripts not found next to $SCRIPT_DIR" >&2
  exit 1
fi

TARGET_BIN="${1:-}"

if [[ -z "$TARGET_BIN" ]]; then
  if command -v droid >/dev/null 2>&1; then
    TARGET_BIN="$(command -v droid)"
  elif [[ -f "$HOME/.factory/bin/droid" ]]; then
    TARGET_BIN="$HOME/.factory/bin/droid"
  elif [[ -f "/opt/homebrew/bin/droid" ]]; then
    TARGET_BIN="/opt/homebrew/bin/droid"
  elif [[ -f "/usr/local/bin/droid" ]]; then
    TARGET_BIN="/usr/local/bin/droid"
  fi
fi

if [[ -z "$TARGET_BIN" || ! -f "$TARGET_BIN" ]]; then
  echo "Error: Factory CLI ('droid') binary not found." >&2
  echo "Please provide the path manually: ./patch-macos.sh /path/to/droid" >&2
  exit 1
fi

# Resolve symlinks to target real binary
REAL_BIN="$TARGET_BIN"
if [[ -L "$TARGET_BIN" ]]; then
  if command -v realpath >/dev/null 2>&1; then
    REAL_BIN="$(realpath "$TARGET_BIN")"
  else
    REAL_BIN="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$TARGET_BIN")"
  fi
  echo "Resolved symlink $TARGET_BIN -> $REAL_BIN"
fi

if [[ ! -w "$REAL_BIN" ]]; then
  echo "Warning: Target binary '$REAL_BIN' is not writable by current user." >&2
  echo "Re-run with sudo if installed in a system directory:" >&2
  echo "  sudo ./patch-macos.sh \"$REAL_BIN\"" >&2
  exit 1
fi

# Collision-resistant backup using mktemp template
BACKUP_BIN="$(mktemp "${REAL_BIN}.bak-XXXXXXXXXX")"
echo "==> Creating backup at: $BACKUP_BIN"
cp -p "$REAL_BIN" "$BACKUP_BIN"

if [[ ! -s "$BACKUP_BIN" ]]; then
  echo "Error: Backup creation failed or produced an empty file." >&2
  rm -f "$BACKUP_BIN"
  exit 1
fi

echo "==> Applying zero-waste titling and keybinding patches..."
# Both patchers run as one guarded unit: if either fails, the backup below
# restores the pre-patch binary (set -e would otherwise abort mid-patch
# without the restore path).
if python3 "$PATCHER" "$REAL_BIN" --test && python3 "$KEYBINDING_PATCHER" "$REAL_BIN" --test; then
  echo ""
  echo "==> SUCCESS: Factory CLI patched successfully!"
  echo "    Binary: $REAL_BIN"
  echo "    Backup: $BACKUP_BIN"
  echo "    Verification: '$REAL_BIN --version' passed."
else
  echo ""
  echo "==> ERROR: Patching failed. Restoring original binary from backup..." >&2
  if cp -pf "$BACKUP_BIN" "$REAL_BIN"; then
    echo "==> Restored original binary successfully." >&2
  else
    echo "==> CRITICAL: Failed to restore backup! Manual intervention required." >&2
    echo "    Original backup preserved at: $BACKUP_BIN" >&2
  fi
  exit 1
fi
