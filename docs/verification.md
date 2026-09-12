# Verification and testing

Run the focused offline checks first:

```bash
python3 tests/test_versions.py --offline
python3 tests/test_keybindings.py
python3 tests/simulate_breakage.py
```

Validate both upstream binary variants, including the latest release:

```bash
python3 tests/test_versions.py --latest
```

Create a disposable local binary for interactive evaluation:

```bash
cp /usr/lib/factory/droid /tmp/droid-keybindings
python3 patches/patch_keybindings.py /tmp/droid-keybindings --test
/tmp/droid-keybindings
```

Run the repository checks:

```bash
flake8 --max-line-length=120 --extend-ignore=E203 patches/ scripts/ tests/
shellcheck scripts/*.sh
shellcheck -s bash factory-ai-droid-cli-rnoz-bin.install
shellcheck -s bash -e SC2034,SC2154,SC2164 PKGBUILD
shfmt -i 2 -ci -d scripts/ factory-ai-droid-cli-rnoz-bin.install
aurscan --rules-only .
```

During an interactive `makepkg`, the package asks before applying each patch
(`Y` by default). Non-interactive builds apply both patches automatically.
When `rg` is already on the build host, the package reuses it instead of
downloading a bundled duplicate; otherwise it verifies and bundles ripgrep.

## Reproducible release regeneration

An owner can regenerate a new or historical upstream version with an explicit
package revision:

```bash
gh workflow run aur-sync.yml \
  --repo rNoz/factory-ai-droid-cli-rnoz \
  --ref main \
  -f upstream_version=X.Y.Z \
  -f package_revision=N \
  -f force_build=true
```

The invariant is `X.Y.Z-N` across `PKGBUILD`, `.SRCINFO`, README, GitHub
release metadata, and AUR. Future normal upstream releases use revision `1`;
package changes increment the current revision.

When the repository already has the exact metadata, no meaningful zero-diff PR
can be created. Use the owner-only publication workflow's `aur_only` repair
mode to republish an existing release or repair AUR metadata from `main`.
