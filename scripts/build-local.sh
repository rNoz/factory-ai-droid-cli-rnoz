#!/usr/bin/env bash
set -euo pipefail

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/factory-ai-droid-build.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT

cp -a \
  PKGBUILD \
  patch_title.py \
  patch_keybindings.py \
  factory-ai-droid-cli-rnoz-bin.install \
  LICENSE \
  "$build_dir/"

cd "$build_dir"
makepkg "$@"
