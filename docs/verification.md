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

For an installed binary, verify that the runtime registry is included in the
same safe rotation rather than relying only on the `--version` smoke test:

```bash
python3 patches/patch_keybindings.py /usr/lib/factory/droid --dry-run
```

When evaluating `Ctrl-I` interactively, use a terminal path that preserves
modified-key information (for example Alacritty with tmux `extended-keys on`
and CSI-u/Kitty forwarding). Legacy terminals encode `Ctrl-I` as the same
byte as `Tab`, so no application-level patch can distinguish those inputs.

Run the repository checks:

```bash
flake8 --max-line-length=120 --extend-ignore=E203 patches/ scripts/ tests/
shellcheck scripts/*.sh
shellcheck -s bash factory-ai-droid-cli-rnoz-bin.install
shellcheck -s bash -e SC2034,SC2154,SC2164 PKGBUILD
shfmt -i 2 -ci -d scripts/ factory-ai-droid-cli-rnoz-bin.install
aurscan --rules-only .
```

During an interactive `makepkg` or `scripts/patch-macos.sh` run, the package
asks before applying each patch (`Y` by default). Non-interactive runs apply
both patches automatically. The macOS script asks before removing its backup
after a successful `--version` smoke test; non-interactive runs remove it
automatically.
When `rg` is already on the build host, the package reuses it instead of
downloading a bundled duplicate; otherwise it verifies and bundles ripgrep.

Maintainer-only release regeneration and publication procedures are documented
in [`maintainer-release.md`](maintainer-release.md).
