# PR-Only Release Automation Adversarial Review

## Scope and reviewers

- Scope: protected `main`, autonomous release PR preparation, merged-release publication, GitHub/AUR idempotency, and secret/event boundaries.
- Reviewers: Droid Gemini 3.8 Flash and Droid GLM-5.3, both run independently against the repository.
- Reconciliation: Gemini identified three blocking defects in the committed implementation; GLM independently found no blocking defects in that same commit but identified seven reliability defects. The blocking findings were accepted and fixed before this record was updated.

## Accepted findings and fixes

| Finding | Fix |
|---|---|
| Empty `gh pr list` returned `null`, preventing PR creation | Use `--jq '.[0].url // empty'`. |
| Shallow checkout made `--force-with-lease` fail for existing release branches | Fetch the remote branch ref before pushing. |
| Human PRs skipped full packaging validation | Run the full validation path for every pull-request event. |
| Publication used mutable `main` | Check out `github.event.pull_request.merge_commit_sha`. |
| Annotated tags were compared by tag-object SHA | Resolve the tag through the commits endpoint. |
| `pkgrel` was not reset after the container bumped `pkgver` | Reset `pkgrel=1` in `build-in-container.sh`. |
| Shell interpolation used untrusted ref text | Pass the PR head ref through `env` before shell comparison. |
| AUR no-op commit handling swallowed real failures | Check the staged diff before committing; propagate actual commit/push failures. |
| AUR and issue messages used `vrelease/v...` | Derive messages from the validated `pkgver`. |
| Release reruns could overwrite assets from a different tree | Pin checkout and release creation to the merge commit and reject tag drift. |

## Remaining operational prerequisite

`RELEASE_TOKEN` is intentionally required and is not present in the repository yet. It must be added as a fine-grained repository secret with only the permissions required for release-branch pushes, pull-request management, release publication, and issue updates. Until then, ordinary CI validation works, but an upstream release cannot complete its automated publication path.

## Verification

The final changes must pass the local release metadata tests, offline patch fixtures, YAML parsing, shell syntax checks, and a live release-PR rehearsal after `RELEASE_TOKEN` is configured. The rehearsal must verify that the release branch PR validates, auto-merges, publishes against its merge SHA, and reruns update rather than duplicate the release.
