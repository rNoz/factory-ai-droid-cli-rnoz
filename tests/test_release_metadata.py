#!/usr/bin/env python3

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/update-release-metadata.py"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/aur-sync.yml"
PUBLISH_WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/publish-release.yml"
SPEC = importlib.util.spec_from_file_location("update_release_metadata", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_pkgrel_resets_when_upstream_version_changes() -> None:
    text = "pkgver=0.217.0\npkgrel=2\n"
    assert MODULE.reset_pkgrel(text, "0.217.0", "0.218.0") == "pkgver=0.217.0\npkgrel=1\n"


def test_pkgrel_is_preserved_for_same_version_rebuilds() -> None:
    text = "pkgver=0.217.0\npkgrel=2\n"
    assert MODULE.reset_pkgrel(text, "0.217.0", "0.217.0") == text


def test_readme_has_single_license_section_and_nested_test_matrix() -> None:
    text = MODULE.README.read_text()
    assert text.count("\n## License\n") == 1
    assert text.count("\n## Unofficial status and licensing\n") == 0
    assert text.count("\n### Tested releases\n") == 1
    assert text.index("## Verification and engineering") < text.index("### Tested releases")


def test_ci_badge_uses_shields_endpoint() -> None:
    text = MODULE.README.read_text()
    assert "img.shields.io/badge/CI%20Build%20%26%20Security-passing-brightgreen" in text
    assert "github/actions/workflow/status/" not in text


def test_release_automation_uses_merge_gated_prs() -> None:
    workflow = WORKFLOW.read_text()
    publication = PUBLISH_WORKFLOW.read_text()
    assert "release/v${UPSTREAM_VER}" in workflow
    assert "secrets.RELEASE_TOKEN" in workflow
    assert "RELEASE_TOKEN repository secret is required" in workflow
    assert "gh pr create" in workflow
    assert "git diff --cached --quiet" in workflow
    assert "git fetch origin \"+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH\"" in workflow
    assert "git push --force-with-lease origin \"$BRANCH\"" in workflow
    assert "--jq '.[0].url // empty'" in workflow
    assert '[ "${{ github.event_name }}" = "pull_request" ]' in workflow
    assert "github.event.pull_request.merged == true" in publication
    assert "github.event.pull_request.head.repo.full_name == github.repository" in publication
    assert "github.event.pull_request.merge_commit_sha" in publication
    assert "ref: ${{ github.event.pull_request.merge_commit_sha }}" in publication
    assert "MERGE_SHA: ${{ github.event.pull_request.merge_commit_sha }}" in publication
    assert "RELEASE_TOKEN repository secret is required" in publication
    assert "/commits/v${UPSTREAM_VER}" in publication
    assert 'git diff --cached --quiet' in publication
    assert '--target "$MERGE_SHA"' in publication


if __name__ == "__main__":
    test_pkgrel_resets_when_upstream_version_changes()
    test_pkgrel_is_preserved_for_same_version_rebuilds()
    test_readme_has_single_license_section_and_nested_test_matrix()
    test_ci_badge_uses_shields_endpoint()
    test_release_automation_uses_merge_gated_prs()
    print("ALL RELEASE METADATA TESTS PASSED")
