# PR-Only Release Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve autonomous release updates while ensuring human changes reach `main` only through pull requests.

**Architecture:** The existing release workflow will create a dedicated release pull request instead of pushing release metadata directly to `main`. A separate post-merge workflow will publish the release and AUR update after that PR is merged. A fine-grained `RELEASE_TOKEN` owned by `rNoz` will authenticate the bot's branch/PR/release operations; ordinary `GITHUB_TOKEN` access will not bypass branch protection.

**Tech Stack:** GitHub Actions YAML, GitHub CLI, Python release metadata script, Arch/AUR packaging.

**Spec:** User request: CI bots must continue autonomous release work, while human contributions are PR-only and only the repository owner can merge.

**Global Constraints**

- `main` must reject direct human pushes, force-pushes, and deletions.
- Release automation may create/update a release branch and its pull request, then merge that PR after required checks pass.
- Only `rNoz` has repository write/admin access.
- Existing release notes, source tarball contents, AUR synchronization, and CI validation behavior must remain intact.
- No credentials may be read or committed; `RELEASE_TOKEN` is referenced only as a GitHub Actions secret.

---

### Task 1: Add regression coverage for PR-based release metadata

**Files:**
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: `scripts/update-release-metadata.py` and repository README.
- Produces: Assertions that generated metadata remains idempotent and release automation uses a dedicated branch/PR model.

- [ ] **Step 1: Write failing tests**

Add tests that assert the workflow contains a release branch name, uses `RELEASE_TOKEN`, creates a pull request, and does not directly push `main` from the release preparation step.

- [ ] **Step 2: Run the focused test**

Run:

```bash
python3 tests/test_release_metadata.py
```

Expected: the new workflow assertions fail before the workflow change.

- [ ] **Step 3: Commit the test-only change**

```bash
git add tests/test_release_metadata.py
git commit -m "test(ci): require PR-based release preparation"
```

### Task 2: Convert release preparation from direct main push to an auto-merged PR

**Files:**
- Modify: `.github/workflows/aur-sync.yml`
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: `build-and-test` packaging artifact and upstream version output.
- Produces: A `release/v<version>` branch, one metadata commit, and an auto-merge-enabled PR targeting `main`.

- [ ] **Step 1: Update workflow triggers and permissions**

Add pull-request validation events for `opened`, `synchronize`, `reopened`, and `closed`; keep publish preparation restricted to main-branch push/schedule/manual runs. Use `secrets.RELEASE_TOKEN` for checkout and GitHub CLI operations that create or push the release branch.

- [ ] **Step 2: Replace the direct metadata push**

In the current `publish` job, create or reset `release/v${UPSTREAM_VER}`, commit `PKGBUILD`, `.SRCINFO`, `README.md`, and `tests/test_versions.py` there, push that branch with `RELEASE_TOKEN`, create or update its PR, and request auto-merge with squash. Do not push `main` from this job.

- [ ] **Step 3: Keep release publication out of preparation**

Remove release-note generation, source-tarball upload, and AUR publication from the preparation job. Those operations move to Task 3 and must run only after the release PR is merged.

- [ ] **Step 4: Run the focused tests and YAML checks**

Run:

```bash
python3 tests/test_release_metadata.py
git diff --check
```

Expected: all release metadata tests pass and the workflow has no whitespace errors.

- [ ] **Step 5: Commit the workflow conversion**

```bash
git add .github/workflows/aur-sync.yml tests/test_release_metadata.py
git commit -m "ci: prepare releases through pull requests"
```

### Task 3: Publish releases only after the bot PR merges

**Files:**
- Create: `.github/workflows/publish-release.yml`
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: merged `release/v<version>` pull request and the merged repository contents.
- Produces: GitHub release/tag, source tarball, AUR synchronization, and resolved breakage issues.

- [ ] **Step 1: Add the merged-PR trigger and guard**

Trigger on `pull_request` `closed` events targeting `main`, and run only when `merged == true` and the head branch matches `release/*`. Check out the resulting `main` commit with `RELEASE_TOKEN`.

- [ ] **Step 2: Reproduce the existing release publication contract**

Port the current release-note fetch, release-note template, source archive file list, release create/update behavior, AUR synchronization, and breakage-issue closure from `aur-sync.yml` without changing their output or package inputs.

- [ ] **Step 3: Make reruns idempotent**

Use `gh release view` to edit/upload an existing release with `--clobber`, or create it when absent. Use the existing package metadata and deterministic archive name so rerunning the merged-PR workflow updates the same release instead of creating duplicates.

- [ ] **Step 4: Add workflow contract tests**

Assert that the publication workflow is merge-gated, uses `RELEASE_TOKEN`, and contains the existing release asset and AUR publication paths.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 tests/test_release_metadata.py
git diff --check
```

Then commit:

```bash
git add .github/workflows/publish-release.yml tests/test_release_metadata.py
git commit -m "ci: publish releases after metadata PR merge"
```

### Task 4: Align repository protection with the automation exception

**Files:**
- No repository source files; configure GitHub repository settings through `gh api`.

**Interfaces:**
- Consumes: PR-based release workflow and repository secret `RELEASE_TOKEN`.
- Produces: Protected `main` with required CI, no direct human pushes, and owner-authenticated bot PR merges.

- [ ] **Step 1: Require PRs and CI on main**

Keep admin enforcement, required `build-and-test`, linear history, conversation resolution, no force-push, and no deletion. Set required approvals to zero because the owner-authenticated release bot cannot approve its own PR; only `rNoz` has write access, so other contributors still cannot merge.

- [ ] **Step 2: Enable auto-merge and verify access**

Enable repository auto-merge, keep squash as the only merge method, and verify that the only collaborator with write access is `rNoz`.

- [ ] **Step 3: Confirm the secret prerequisite**

Verify that `RELEASE_TOKEN` exists without reading its value. If absent, stop before claiming the automation path is live; the workflow must not fall back to `GITHUB_TOKEN` for protected-branch operations.

### Task 5: Adversarial verification and end-to-end release rehearsal

**Files:**
- Review: all files changed in Tasks 1–4.
- Record: `docs/adversarial-reviews/2026-09-11-pr-only-release-automation.md`

**Interfaces:**
- Consumes: completed workflow and protection configuration.
- Produces: independent evidence that human direct pushes are blocked, bot PR automation works, and release publication is idempotent.

- [ ] **Step 1: Run an independent code/workflow review**

The reviewer must distrust the implementation, inspect token scope and event permissions, verify fork-PR safety, check branch-name guards, and look for paths that can publish or push without the intended merge gate.

- [ ] **Step 2: Run local gates**

Run:

```bash
python3 tests/test_release_metadata.py
python3 tests/test_versions.py --offline
git diff --check
```

- [ ] **Step 3: Add the fine-grained token secret**

Configure `RELEASE_TOKEN` as a repository secret with only the permissions needed to push the release branch, create/update/merge its PR, and publish the GitHub release. Never print or inspect its value.

- [ ] **Step 4: Rehearse through CI**

Force the workflow to detect the current upstream version, confirm it creates/updates the release PR, confirm `build-and-test` passes on that PR, confirm auto-merge updates `main`, and confirm the merged-PR workflow creates or updates `v<version>` and its source archive.

- [ ] **Step 5: Verify idempotency**

Rerun the merged-PR publication workflow and confirm the same tag/release and archive are updated rather than duplicated. Record run IDs, release URL, asset name, and final protection output in the adversarial review record.
