# Maintainer release procedures

This document contains release and rebuild workflows that are useful to
maintainers but are not part of normal package installation.

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

The invariant is `X.Y.Z-N` across `PKGBUILD`, `.SRCINFO`, the GitHub release
metadata, and AUR. Future normal upstream releases use revision `1`; package
changes increment the current revision.

When the repository already has the exact metadata, no meaningful zero-diff PR
can be created. Use the owner-only publication workflow's `aur_only` repair
mode to republish an existing release or repair AUR metadata from `main`.
