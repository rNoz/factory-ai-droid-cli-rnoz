# Factory.ai Droid CLI (rnoz version)

<div align="center">

> Always-fresh, automated packaging for [Factory CLI](https://app.factory.ai) (`droid`) featuring zero-waste deterministic session titling, hardware-optimal lean packaging, and supply-chain security auditing.

[![CI Build & Security](https://github.com/rNoz/factory-ai-droid-cli-rnoz/actions/workflows/aur-sync.yml/badge.svg?branch=main)](https://github.com/rNoz/factory-ai-droid-cli-rnoz/actions/workflows/aur-sync.yml)
[![AUR version](https://img.shields.io/aur/version/factory-ai-droid-cli-rnoz-bin?logo=archlinux)](https://aur.archlinux.org/packages/factory-ai-droid-cli-rnoz-bin)
[![Security: aurscan](https://img.shields.io/badge/security-aurscan%20v0.9.0-34d399?logo=shield&logoColor=white)](https://github.com/manticore-projects/aurscan)
[![License](https://img.shields.io/badge/license-Apache--2.0%20%2F%20Proprietary-blue.svg)](LICENSE)
[![Arch](https://img.shields.io/badge/arch-x86__64%20%7C%20aarch64%20%7C%20macOS-informational)]()
[![Python](https://img.shields.io/badge/python-3.8%2B-blue?logo=python&logoColor=white)](https://python.org)
[![Upstream Tests](https://img.shields.io/badge/tested%20releases-7%20(100%25%20PASS)-brightgreen)]()

</div>

---

## Why this exists

1. **Zero Titling Token Waste**: Factory CLI by default fires an unconfigurable background LLM call (Claude Haiku 4.5) on the first prompt of every interactive session, consuming an estimated ~300–500 input and ~10–25 output credits per conversation. This package enforces instant, local deterministic titling—saving API credits and eliminating initial latency while keeping terminal tab titles and session history logs intact.
2. **Hardware-Optimal Lean Binary**: Unlike generic packages that either force AVX2 (crashing older/virtualized CPUs with `SIGILL`) or ship bloated multi-binary bundles, `factory-ai-droid-cli-rnoz-bin` inspects the host CPU at build/package time and installs **only one single binary** (`/usr/lib/factory/droid`). Modern CPUs receive the AVX2-optimized build; legacy/VM/sandbox CPUs receive the baseline build. Package footprint is cut in half (~80 MB) with zero runtime wrapper overhead.
3. **Always Fresh & Autonomous**: Automated CI checks Factory AI upstream releases 3× daily, validates patches against multiple releases in an official Arch Linux container, and publishes updates with zero manual intervention.
4. **Supply Chain Security & Linters**: Every build is scanned with [aurscan](https://github.com/manticore-projects/aurscan) (`v0.9.0`, SHA-256 pinned) to guarantee clean, non-malicious packaging scripts. Code is strictly validated with `flake8`, `shellcheck`, and `shfmt`.
5. **Clean & Lean Packaging**: Only bundles what `droid` actually requires. Includes bundled `ripgrep` with optional fallback to system `ripgrep`. Upstream binaries are fetched dynamically during installation and validated with fail-closed SHA-256 checks.

---

## Supported Architectures & Platforms

| Platform | Architecture | Upstream Binary Stream | Packaging Behavior | Testing Status |
| :--- | :--- | :--- | :--- | :--- |
| **Arch Linux** | `x86_64` (AVX2 supported) | `linux/x64/droid` | Installs AVX2-optimized single binary | **Verified** (CI & Arch container) |
| **Arch Linux** | `x86_64` (No AVX2 / VM) | `linux/x64-baseline/droid` | Installs baseline single binary (zero `SIGILL`) | **Verified** (CI & Arch container) |
| **Arch Linux** | `aarch64` | `linux/arm64/droid` | Installs native ARM64 single binary | Build verified |
| **macOS** | Apple Silicon (`arm64`) | Official Homebrew / curl | In-place patch with collision-resistant backup | *Untested / Experimental* |
| **macOS** | Intel (`x86_64`) | Official Homebrew / curl | In-place patch with collision-resistant backup | *Untested / Experimental* |

> **Testing Scope**: Arch Linux packaging, AVX2 execution, non-AVX2 baseline fallback, and byte-exact patch replacement are 100% automated, tested, and smoke-tested in CI using official Arch Linux containers. The macOS companion helper (`scripts/patch-macos.sh`) is provided as an experimental helper and has not yet been tested on macOS.

*Note: Maintainers and automated builders can explicitly force a variant via `DROID_ARCH_VARIANT=baseline` or `DROID_ARCH_VARIANT=avx2` when invoking `makepkg`.*

---

## Installation

### Arch Linux (AUR / `makepkg`)

Install via your preferred AUR helper:

```bash
yay -S factory-ai-droid-cli-rnoz-bin
```

Or build manually from source:

```bash
git clone https://github.com/rNoz/factory-ai-droid-cli-rnoz.git
cd factory-ai-droid-cli-rnoz
makepkg -si
```

*Provides and conflicts with `droid`, `factory-cli`, and `factory-cli-bin`.*

### macOS (Experimental)

> *Testing has focused on Arch Linux. The macOS patcher is provided as an untested helper script.*

Run the standalone patcher against an existing Factory CLI installation:

```bash
git clone https://github.com/rNoz/factory-ai-droid-cli-rnoz.git
cd factory-ai-droid-cli-rnoz
./scripts/patch-macos.sh
```

*Locates `droid`, resolves symlinks, creates collision-resistant backups (`droid.bak-*`), applies byte-safe patches, and validates execution.*

---

## Repository Structure

```text
├── PKGBUILD                              # Arch Linux package specification (hardware-optimal)
├── .SRCINFO                              # Generated AUR package metadata
├── patch-droid.py                        # Core context-bounded byte-exact patch engine
├── factory-ai-droid-cli-rnoz-bin.install # Pacman post-install notice
├── LICENSE                               # Apache-2.0 License
├── scripts/
│   ├── patch-macos.sh                    # Standalone macOS patcher with backup rotation
│   ├── build-in-container.sh             # Isolated Arch Linux container build script
│   └── fetch-changelog.py                # Upstream release notes scraper
└── tests/
    ├── test_versions.py                  # Multi-version matrix (AVX2 + baseline) & fixtures
    └── simulate_breakage.py              # Fail-closed breakage simulation suite
```

---

## Verification & Testing

```bash
# Verify CLI runs cleanly
droid --version

# Inspect patch state directly
python3 patch-droid.py /usr/lib/factory/droid --check
# Status: patched

# Run offline synthetic tests
python3 tests/test_versions.py --offline

# Run multi-version test suite across both AVX2 and baseline streams
python3 tests/test_versions.py

# Run failure and recovery simulations
python3 tests/simulate_breakage.py

# Run linters locally
flake8 --max-line-length=120 --extend-ignore=E203 patch-droid.py scripts/ tests/
shellcheck scripts/*.sh
shellcheck -s bash factory-ai-droid-cli-rnoz-bin.install
shellcheck -s bash -e SC2034,SC2154,SC2164 PKGBUILD
shfmt -i 2 -ci -d scripts/ factory-ai-droid-cli-rnoz-bin.install
aurscan --rules-only .
```

---

## Engineering & Safety

- **Byte-Exact Patching**: Replaces the internal titling guard with space-padded JS comments (`if(true)return null;/* ... */`), preserving 100% byte offset equivalence to guarantee no V8 snapshot or symbol alignment breakage.
- **Fail-Safe Gate**: `patch-droid.py` verifies contextual byte-string markers (`formatTitle`, `firstUserText`, `isSessionTitleManuallySet`) and runs an automated smoke test before accepting any binary.
- **CI Test Matrix**: Releases are gated on offline synthetic test fixtures and multi-version matrix tests (`tests/test_versions.py`) across both `x64` and `x64-baseline` binary streams across 7 versions, package installation via `pacman -U`, and binary smoke checks inside an official `archlinux:base-devel` container.
- **aurscan Security Guard**: Integrated in CI with pinned binary (`v0.9.0`) and pinned SHA-256 hash to audit package scripts against malicious patterns.
- **Self-Healing & Breakage Alerts**: Network downloads implement exponential backoff retries. If an upstream update modifies minification patterns, CI automatically files a clean GitHub breakage issue with target version, failure logs, and links to the [Official Factory Changelog](https://docs.factory.ai/changelog/release-notes).
- **Pure Standard Library**: Zero external Python dependencies required (`python >= 3.8`).
