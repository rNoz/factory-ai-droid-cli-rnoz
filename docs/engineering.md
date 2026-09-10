# Engineering and safety

- **Byte-exact title patch:** `patches/patch_title.py` replaces the contextual
  title guard with a same-length JavaScript comment, preserving binary offsets.
- **Keybinding rotation:** `patches/patch_keybindings.py` identifies the
  serialized keymap, guarded runtime dispatch, model matcher, and human-facing
  chord hints. It rotates editor → `Ctrl-G`, model cycling → `Ctrl-P`, and
  queued-message pull → `Ctrl-Q`.
- **Fail closed:** Minified identifiers are inferred from structural anchors.
  Missing, ambiguous, partially patched, or conflicting layouts abort without
  writing. Action guards move with their action, binary size is preserved, and
  an already-patched binary is accepted only when its complete layout matches.
- **Release validation:** CI runs offline fixtures, the latest upstream
  x64/baseline matrix, Arch packaging, smoke tests, and `aurscan`.
- **Supply-chain scope:** The README image is documentation only. Release
  source tarballs contain packaging metadata and patch sources, never the image
  or downloaded upstream binaries.
