#!/usr/bin/env bash
set -euo pipefail

UPSTREAM_VER="$1"

echo "==> Updating pacman and installing dependencies..."
pacman -Syu --noconfirm git python curl

echo "==> Setting up non-root build user..."
useradd -m -d /home/builduser builduser
mkdir -p /build
cp -r /github/workspace/. /build/
chown -R builduser:builduser /build

cd /build

echo "==> Updating PKGBUILD version to ${UPSTREAM_VER}..."
sed -i "s/^pkgver=.*/pkgver=${UPSTREAM_VER}/" PKGBUILD
sed -i "s/^pkgrel=.*/pkgrel=1/" PKGBUILD

echo "==> Updating .SRCINFO..."
su builduser -c "makepkg --printsrcinfo > .SRCINFO"

echo "==> Compiling package with makepkg..."
su builduser -c "makepkg -f --noconfirm"

echo "==> Testing package installation and smoke testing droid binary..."
pacman -U --noconfirm factory-ai-droid-cli-rnoz-bin-*.pkg.tar.zst
droid --version
python3 patch-droid.py /usr/lib/factory/droid --check

echo "==> Copying built package back to workspace..."
cp factory-ai-droid-cli-rnoz-bin-*.pkg.tar.zst PKGBUILD .SRCINFO /github/workspace/
chmod 644 /github/workspace/factory-ai-droid-cli-rnoz-bin-*.pkg.tar.zst /github/workspace/PKGBUILD /github/workspace/.SRCINFO
echo "==> Arch Linux container build and smoke test completed successfully!"
