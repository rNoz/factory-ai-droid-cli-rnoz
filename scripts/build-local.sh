#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/factory-ai-droid-build.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT

cp -aL \
  "$repo_root/PKGBUILD" \
  "$repo_root/patch_title.py" \
  "$repo_root/patch_keybindings.py" \
  "$repo_root/factory-ai-droid-cli-rnoz-bin.install" \
  "$repo_root/LICENSE" \
  "$build_dir/"

cd "$build_dir"
makepkg "$@"
