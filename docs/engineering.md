# Engineering and safety

## Patch architecture

- **Title patch:** `patches/patch_title.py` finds the title-specific
  `isNonInteractiveCLIMode()` guard using surrounding title markers and replaces
  it with a same-length JavaScript comment. It never relies on a fixed offset.
- **Keybinding patch:** `patches/patch_keybindings.py` cross-validates the
  serialized keymap, guarded runtime dispatch, generic runtime key-ID
  registry, model matcher, and human-facing chord hints before changing
  anything. It rotates editor → `Ctrl-G`, model cycling → `Ctrl-P`, and
  queued-message pull → `Ctrl-I`. For v0.219+ binary-record tables, the
  physical key labels and records remain unchanged; only the action dispatch
  and associated runtime descriptors move.
- **Upstream layout compatibility:** Releases through v0.218 use action-linked
  keymap records; v0.219 introduced binary-record keymap entries. Both layouts
  have separate structural validation and idempotent, same-length replacements.
- **Minifier tolerance:** Action identifiers are captured from structural
  anchors, so upstream renames do not matter when the surrounding layout stays
  compatible.
- **Fail-closed safety:** Missing, ambiguous, conflicting, or partially patched
  layouts abort before writing. Guards move with their actions, replacements
  preserve binary length, runtime string IDs remain resolvable, and an old
  binary-record state with relabeled physical keys is rejected rather than
  remapped again.

## Terminal protocol requirement

The runtime matcher can distinguish `Ctrl-I` from `Tab` only when the terminal
forwards modified keys through a protocol such as Kitty/CSI-u. The package
does not claim that distinction on a legacy terminal path where both chords
arrive as byte `0x09`. Alacritty setups using tmux `extended-keys on` provide
the required forwarding path; users on legacy terminals should choose another
queue shortcut rather than expecting `Ctrl-I` to be distinguishable.

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
