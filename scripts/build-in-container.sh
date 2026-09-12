#!/usr/bin/env bash
set -euo pipefail

UPSTREAM_VER="$1"
PACKAGE_REVISION="${2:-1}"
build_dir="$(mktemp -d /tmp/factory-ai-droid-build.XXXXXX)"
trap 'rm -rf "$build_dir"' EXIT

echo "==> Updating pacman and installing dependencies..."
pacman -Syu --noconfirm git python curl

echo "==> Setting up non-root build user..."
useradd -m -d /home/builduser builduser
cp -r /github/workspace/. "$build_dir/"
chown -R builduser:builduser "$build_dir"

cd "$build_dir"

echo "==> Updating PKGBUILD version to ${UPSTREAM_VER}-${PACKAGE_REVISION}..."
sed -i -e "s/^pkgver=.*/pkgver=${UPSTREAM_VER}/" -e "s/^pkgrel=.*/pkgrel=${PACKAGE_REVISION}/" PKGBUILD

echo "==> Updating .SRCINFO..."
su builduser -c "makepkg --printsrcinfo > .SRCINFO"

echo "==> Compiling package with makepkg..."
su builduser -c "makepkg -f --noconfirm"

echo "==> Testing package installation and smoke testing droid binary..."
package_file="$(find "$build_dir" -maxdepth 1 -name 'factory-ai-droid-cli-rnoz-bin-*.pkg.tar.zst' -print -quit)"
pacman -U --noconfirm "$package_file"
droid --version
python3 patches/patch_title.py /usr/lib/factory/droid --check

echo "==> Copying packaging metadata back to workspace..."
cp "$build_dir"/PKGBUILD "$build_dir"/.SRCINFO /github/workspace/
chmod 644 /github/workspace/PKGBUILD /github/workspace/.SRCINFO
echo "==> Arch Linux container build and smoke test completed successfully!"
