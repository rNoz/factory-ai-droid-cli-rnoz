# Engineering and safety

## Patch architecture

- **Title patch:** `patches/patch_title.py` finds the title-specific
  `isNonInteractiveCLIMode()` guard using surrounding title markers and replaces
  it with a same-length JavaScript comment. It never relies on a fixed offset.
- **Keybinding patch:** `patches/patch_keybindings.py` cross-validates the
  serialized keymap, guarded runtime dispatch, generic runtime key-ID
  registry, model matcher, and human-facing chord hints before changing
  anything. It rotates editor → `Ctrl-G`, model cycling → `Ctrl-P`, and
  queued-message pull → `Ctrl-I`.
- **Upstream layout compatibility:** Releases through v0.218 use action-linked
  keymap records; v0.219 introduced binary-record keymap entries. Both layouts
  have separate structural validation and idempotent, same-length replacements.
- **Minifier tolerance:** Action identifiers are captured from structural
  anchors, so upstream renames do not matter when the surrounding layout stays
  compatible.
- **Fail-closed safety:** Missing, ambiguous, conflicting, or partially patched
  layouts abort before writing. Guards move with their actions, replacements
  preserve binary length, runtime string IDs remain resolvable, and a full
  already-patched layout is required for idempotent acceptance.

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

### AUR helper interactive prompt detection

Most AUR helpers (`yay`, `paru`, `pikaur`, `aurman`, etc.) invoke `makepkg`
internally with `--noconfirm` so `pacman` does not prompt when resolving build
dependencies. In standard `makepkg`, this automatically sets
`PACMAN_OPTS=("--noconfirm")`. Naively checking `PACMAN_OPTS` inside `PKGBUILD`
would falsely treat interactive terminal sessions under AUR helpers as headless,
silently bypassing user confirmation prompts for custom patches (zero-waste
titling and keybindings).

To balance ease of use and interactive customization:
1. `PKGBUILD` defines `has_user_noconfirm()`, which inspects ancestor process
   command lines in `/proc`. If an AUR helper is detected in the process tree,
   it checks whether `--noconfirm` was genuinely passed by the user to the helper
   itself, rather than injected by the helper into `makepkg`.
2. When invoked directly via `makepkg`, it checks `PACMAN_OPTS`.
3. Explicit automation overrides (`DROID_NONINTERACTIVE=1`, or specific patch
   toggles `DROID_APPLY_TITLING_PATCH=0/1` and `DROID_APPLY_KEYBINDINGS_PATCH=0/1`)
   short-circuit inspection immediately.
4. Container and CI builds (`scripts/build-in-container.sh`) enforce
   `DROID_NONINTERACTIVE=1`, ensuring headless and automated pipelines are 100%
   fail-closed without waiting on user input.

## Release and supply-chain controls

CI runs offline fixtures, the latest upstream x64/baseline matrix, Arch
packaging, smoke tests, shell/Python linters, and pinned `aurscan` checks.
Release source tarballs contain only packaging metadata and patch sources;
the README image and downloaded upstream binaries are never included.
