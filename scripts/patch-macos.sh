#!/usr/bin/env bash
# patch-macos.sh — Apply zero-waste titling patch to Factory CLI on macOS
#
# Usage:
#   ./patch-macos.sh                  # Auto-detects droid in PATH or standard dirs
#   ./patch-macos.sh /path/to/droid   # Patches a specific droid binary

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCHER="$SCRIPT_DIR/../patches/patch_title.py"
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

INTERACTIVE=false
if [[ -t 0 && -t 1 ]]; then
  INTERACTIVE=true
elif (exec </dev/tty && exec >/dev/tty) 2>/dev/null; then
  INTERACTIVE=true
fi

should_apply_patch() {
  local label="$1"
  local env_name=""
  if [[ "$label" == *"titling"* ]]; then
    env_name="DROID_APPLY_TITLING_PATCH"
  elif [[ "$label" == *"keybinding"* ]]; then
    env_name="DROID_APPLY_KEYBINDINGS_PATCH"
  fi

  if [[ -n "$env_name" && -n "${!env_name:-}" ]]; then
    if [[ "${!env_name}" =~ ^[Nn0]$ ]]; then
      return 1
    elif [[ "${!env_name}" =~ ^[Yy1]$ ]]; then
      return 0
    fi
  fi

  if [[ "$INTERACTIVE" != true ]]; then
    return 0
  fi

  local answer
  printf "Apply %s patch? [Y/n] " "$label" >/dev/tty
  read -r answer </dev/tty
  [[ ! "$answer" =~ ^[Nn]$ ]]
}

apply_patch_if_requested() {
  local label="$1"
  local patcher="$2"
  if should_apply_patch "$label"; then
    python3 "$patcher" "$REAL_BIN" --test
  else
    echo "    Skipping ${label} patch."
  fi
}

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
if apply_patch_if_requested "deterministic titling" "$PATCHER" &&
  apply_patch_if_requested "cross-harness keybindings" "$KEYBINDING_PATCHER" &&
  "$REAL_BIN" --version >/dev/null; then
  echo ""
  echo "==> SUCCESS: Factory CLI patched successfully!"
  echo "    Binary: $REAL_BIN"
  echo "    Backup: $BACKUP_BIN"
  echo "    Verification: '$REAL_BIN --version' passed."
  if [[ "$INTERACTIVE" == true ]]; then
    read -r -p "Remove backup '$BACKUP_BIN'? [Y/n] " answer </dev/tty
    if [[ "$answer" =~ ^[Nn]$ ]]; then
      echo "    Backup preserved at: $BACKUP_BIN"
    else
      rm -f "$BACKUP_BIN"
      echo "    Backup removed."
    fi
  else
    rm -f "$BACKUP_BIN"
    echo "    Backup removed (non-interactive mode)."
  fi
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
