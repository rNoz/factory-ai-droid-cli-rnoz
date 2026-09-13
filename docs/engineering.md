# Engineering and safety

## Patch architecture

- **Title patch:** `patches/patch_title.py` finds the title-specific
  `isNonInteractiveCLIMode()` guard using surrounding title markers and replaces
  it with a same-length JavaScript comment. It never relies on a fixed offset.
- **Keybinding patch:** `patches/patch_keybindings.py` cross-validates the
  serialized keymap, guarded runtime dispatch, model matcher, and human-facing
  chord hints before changing anything. It rotates editor → `Ctrl-G`, model
  cycling → `Ctrl-P`, and queued-message pull → `Ctrl-I`.
- **Minifier tolerance:** Action identifiers are captured from structural
  anchors, so upstream renames do not matter when the surrounding layout stays
  compatible.
- **Fail-closed safety:** Missing, ambiguous, conflicting, or partially patched
  layouts abort before writing. Guards move with their actions, replacements
  preserve binary length, and a full already-patched layout is required for
  idempotent acceptance.

## Packaging behavior

- Interactive `makepkg` and `scripts/patch-macos.sh` ask before each patch and
  default to applying it. Non-interactive runs apply both patches without
  prompting. The macOS script asks before removing its backup after a
  successful `--version` smoke test; non-interactive runs remove it
  automatically.
- The package prefers a system `rg` when available. If none is available at
  build time, it downloads and verifies a bundled ripgrep fallback.
- Arch builds select one CPU-appropriate Droid binary and smoke-test it.
  Apple Silicon macOS is verified through the post-update patch script; Intel
  macOS remains unverified.

## Release and supply-chain controls

CI runs offline fixtures, the latest upstream x64/baseline matrix, Arch
packaging, smoke tests, shell/Python linters, and pinned `aurscan` checks.
Release source tarballs contain only packaging metadata and patch sources;
the README image and downloaded upstream binaries are never included.
