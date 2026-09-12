#!/usr/bin/env python3

import hashlib
import importlib.util
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/update-release-metadata.py"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/aur-sync.yml"
PUBLISH_WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/publish-release.yml"
INSTALL = Path(__file__).resolve().parents[1] / "factory-ai-droid-cli-rnoz-bin.install"
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


def test_pkgrel_increments_for_same_version_package_rebuilds() -> None:
    text = "pkgver=0.217.0\npkgrel=2\n"
    assert MODULE.bump_pkgrel(text) == "pkgver=0.217.0\npkgrel=3\n"


def test_pkgrel_can_be_set_for_release_metadata() -> None:
    text = "pkgver=0.217.0\npkgrel=1\n"
    assert MODULE.set_pkgrel(text, 3) == "pkgver=0.217.0\npkgrel=3\n"


def test_srcinfo_revision_tracks_package_metadata() -> None:
    text = "pkgver = 0.217.0\npkgrel = 1\n"
    assert MODULE.update_srcinfo(text, "0.217.0", 3) == "pkgver = 0.217.0\npkgrel = 3\n"


def test_pkgbuild_checksums_match_packaged_sources() -> None:
    text = MODULE.PKGBUILD.read_text()
    for filename in ("patch_keybindings.py", "factory-ai-droid-cli-rnoz-bin.install"):
        digest = hashlib.sha256((MODULE.ROOT / filename).read_bytes()).hexdigest()
        assert f"'{digest}'" in text


def test_readme_has_single_license_section_and_nested_test_matrix() -> None:
    text = MODULE.README.read_text()
    assert text.count("\n## License\n") == 1
    assert text.count("\n## Unofficial status and licensing\n") == 0
    assert text.count("\n### Tested releases\n") == 1
    assert text.index("## Verification and engineering") < text.index("### Tested releases")
    assert "Current package revision:" in text


def test_ci_badge_uses_shields_endpoint() -> None:
    text = MODULE.README.read_text()
    assert "img.shields.io/badge/CI%20Build%20%26%20Security-passing-brightgreen" in text
    assert "github/actions/workflow/status/" not in text


def test_release_automation_uses_merge_gated_prs() -> None:
    workflow = WORKFLOW.read_text()
    publication = PUBLISH_WORKFLOW.read_text()
    assert "aur_only:" in publication
    assert "Repair AUR metadata from current main" in publication
    assert "if: inputs.aur_only != true" in publication
    assert "package_revision:" in workflow
    assert "Override package revision" in workflow
    assert '--set-pkgrel "$PACKAGE_REVISION"' in workflow
    assert "GH_TOKEN: ${{ secrets.RELEASE_TOKEN }}" in publication
    assert 'PACKAGE_VERSION="${UPSTREAM_VER}-${PKGREL}"' in publication
    assert 'RELEASE_TAG="v${PACKAGE_VERSION}"' in publication
    assert 'gh release create "$RELEASE_TAG"' in publication
    assert 'factory-ai-droid-cli-rnoz-bin-${PACKAGE_VERSION}.src.tar.gz' in publication
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
    assert "workflow_dispatch" in publication
    assert "github.event.pull_request.merge_commit_sha" in publication
    assert "inputs.merge_sha || github.event.pull_request.merge_commit_sha" in publication
    assert "MERGE_SHA: ${{ github.event_name == 'workflow_dispatch' && inputs.merge_sha" in publication
    assert 'commits/$RELEASE_TAG' in publication
    assert "/github/workspace/PKGBUILD" not in publication
    assert publication.index('git -C /tmp/aur-repo checkout -B master origin/master') < publication.index('cp PKGBUILD')
    assert 'git diff --cached --quiet' in publication
    assert '--target "$MERGE_SHA"' in publication
    assert '--set-pkgrel "$PACKAGE_REVISION"' in workflow
    assert "PACKAGE_CHANGE" in workflow
    assert "chore(release): prepare" in workflow


def test_upgrade_notice_reports_the_installed_version() -> None:
    result = subprocess.run(
        ["bash", "-c", f"source {INSTALL}; post_upgrade 0.218.0 0.217.0-2"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "upgraded to version 0.218.0" in result.stdout
    assert "upgraded to version 0.217.0-2" not in result.stdout


if __name__ == "__main__":
    test_pkgrel_resets_when_upstream_version_changes()
    test_pkgrel_is_preserved_for_same_version_rebuilds()
    test_pkgrel_increments_for_same_version_package_rebuilds()
    test_pkgrel_can_be_set_for_release_metadata()
    test_srcinfo_revision_tracks_package_metadata()
    test_pkgbuild_checksums_match_packaged_sources()
    test_readme_has_single_license_section_and_nested_test_matrix()
    test_ci_badge_uses_shields_endpoint()
    test_release_automation_uses_merge_gated_prs()
    test_upgrade_notice_reports_the_installed_version()
    print("ALL RELEASE METADATA TESTS PASSED")
