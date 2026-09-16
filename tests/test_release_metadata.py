#!/usr/bin/env python3

import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/update-release-metadata.py"
DETECTOR = Path(__file__).resolve().parents[1] / "scripts/check-upstream-version.py"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/aur-sync.yml"
PUBLISH_WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/publish-release.yml"
CONTAINER = Path(__file__).resolve().parents[1] / "scripts/build-in-container.sh"
LOCAL_BUILD = Path(__file__).resolve().parents[1] / "scripts/build-local.sh"
MAINTAINER_DOC = Path(__file__).resolve().parents[1] / "docs/maintainer-release.md"
INSTALL = Path(__file__).resolve().parents[1] / "factory-ai-droid-cli-rnoz-bin.install"
SPEC = importlib.util.spec_from_file_location("update_release_metadata", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
DETECTOR_SPEC = importlib.util.spec_from_file_location("check_upstream_version", DETECTOR)
DETECTOR_MODULE = importlib.util.module_from_spec(DETECTOR_SPEC)
assert DETECTOR_SPEC.loader is not None
DETECTOR_SPEC.loader.exec_module(DETECTOR_MODULE)


def test_upstream_detector_parses_first_semantic_ver() -> None:
    text = '<script>VER="0.219.0"; VER="0.999.0"</script>'
    assert DETECTOR_MODULE.parse_version(text) == "0.219.0"


def test_upstream_detector_rejects_missing_or_malformed_ver() -> None:
    for text in ('<script>VERSION="0.219.0"</script>', '<script>VER="latest"</script>'):
        try:
            DETECTOR_MODULE.parse_version(text)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed upstream version was accepted")


def test_upstream_detector_validates_owner_override() -> None:
    assert DETECTOR_MODULE.validate_version("0.219.0") == "0.219.0"
    for version in ("0.219", "v0.219.0", "0.219.0-1"):
        try:
            DETECTOR_MODULE.validate_version(version)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid override was accepted: {version}")


def test_upstream_detector_cli_prints_owner_override() -> None:
    result = subprocess.run(
        ["python3", str(DETECTOR), "--override", "0.219.0"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "0.219.0\n"


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


def test_pkgver_can_be_set_for_release_metadata() -> None:
    text = "pkgver=0.217.0\npkgrel=1\n"
    assert MODULE.set_pkgver(text, "0.218.0") == "pkgver=0.218.0\npkgrel=1\n"


def test_standalone_metadata_update_synchronizes_all_version_fields() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative in ("PKGBUILD", ".SRCINFO", "README.md", "tests/test_versions.py"):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(MODULE.ROOT / relative, destination)

        original_paths = MODULE.ROOT, MODULE.PKGBUILD, MODULE.README, MODULE.VERSION_LIST
        MODULE.ROOT = root
        MODULE.PKGBUILD = root / "PKGBUILD"
        MODULE.README = root / "README.md"
        MODULE.VERSION_LIST = root / "tests/test_versions.py"
        original_argv = sys.argv
        sys.argv = ["update-release-metadata.py", "0.219.0", "--set-pkgrel", "4"]
        try:
            assert MODULE.main() == 0
        finally:
            sys.argv = original_argv
            MODULE.ROOT, MODULE.PKGBUILD, MODULE.README, MODULE.VERSION_LIST = original_paths

        assert "pkgver=0.219.0\npkgrel=4\n" in (root / "PKGBUILD").read_text()
        srcinfo = (root / ".SRCINFO").read_text()
        assert re.search(r"^\s*pkgver = 0.219.0$", srcinfo, re.MULTILINE)
        assert re.search(r"^\s*pkgrel = 4$", srcinfo, re.MULTILINE)
        readme = (root / "README.md").read_text()
        assert "Current package revision:" not in readme
        # The tested-release table is regenerated as centered HTML between markers.
        assert readme.count("<!-- tested-releases:start -->") == 1
        assert readme.count("<!-- tested-releases:end -->") == 1
        assert '<table align="center">' in readme
        assert "| linux x86_64 avx2 | linux x86_64 |" not in readme
        assert 'alt="0.219.0 x64 AVX2"' in readme
        versions = MODULE.configured_versions()
        assert f"tested%20releases-{len(versions)}-informational" in readme


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
    assert "Current package revision:" not in text


def test_ci_badge_reflects_real_workflow_status() -> None:
    text = MODULE.README.read_text()
    badge = "github.com/rNoz/factory-ai-droid-cli-rnoz/actions/workflows/aur-sync.yml/badge.svg"
    assert badge in text
    assert "img.shields.io/badge/CI%20Build%20%26%20Security-passing" not in text
    assert "github/actions/workflow/status/" not in text


def test_release_automation_uses_merge_gated_prs() -> None:
    workflow = WORKFLOW.read_text()
    publication = PUBLISH_WORKFLOW.read_text()
    assert "upstream_version:" in workflow
    assert "Override upstream Droid version" in workflow
    assert "fetch-depth: 0" in workflow
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
    refresh_section = workflow[workflow.index("name: refresh release pull request") :]
    assert "persist-credentials: true" in refresh_section


def test_upgrade_notice_reports_the_installed_version() -> None:
    result = subprocess.run(
        ["bash", "-c", f"source {INSTALL}; post_upgrade 0.218.0 0.217.0-2"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "upgraded to version 0.218.0" in result.stdout
    assert "upgraded to version 0.217.0-2" not in result.stdout


def test_metadata_agrees_on_version_and_revision() -> None:
    pkgbuild = MODULE.PKGBUILD.read_text()
    version = re.search(r"^pkgver=(.+)$", pkgbuild, re.MULTILINE).group(1)
    pkgrel = re.search(r"^pkgrel=(\d+)$", pkgbuild, re.MULTILINE).group(1)
    srcinfo = (MODULE.ROOT / ".SRCINFO").read_text()
    assert re.search(rf"^\s*pkgver = {re.escape(version)}$", srcinfo, re.MULTILINE)
    assert re.search(rf"^\s*pkgrel = {pkgrel}$", srcinfo, re.MULTILINE)
    readme = MODULE.README.read_text()
    assert "Current package revision:" not in readme
    versions = MODULE.configured_versions()
    assert version in versions
    assert f'alt="{version} x64 AVX2"' in readme
    assert re.search(rf"tested%20releases-{len(versions)}-informational", readme)


def test_release_repair_guards_are_pinned() -> None:
    workflow = WORKFLOW.read_text()
    publication = PUBLISH_WORKFLOW.read_text()
    # An explicit package_revision dispatch always publishes, even without force_build.
    assert '[ -n "$REQUESTED_REL" ]' in workflow
    # .SRCINFO edits are package changes and must mint exactly one revision.
    assert r"\.SRCINFO$|patches/" in workflow
    # README changes are documentation-only and do not change package metadata.
    assert "- 'README.md'" not in workflow
    # Release assets and AUR pushes heal .SRCINFO against the checked-out PKGBUILD.
    assert "pkgver/pkgrel fields not found" in publication
    # AUR publish refuses checkouts whose package files differ from current main.
    assert "git diff --quiet FETCH_HEAD HEAD" in publication
    assert "skipping AUR publish to avoid regressing AUR" in publication


def test_container_builds_the_calculated_package_revision() -> None:
    container = CONTAINER.read_text()
    workflow = WORKFLOW.read_text()
    assert 'PACKAGE_REVISION="${2:-1}"' in container
    assert "pkgrel=${PACKAGE_REVISION}" in container
    invocation = (
        'build-in-container.sh "${{ steps.check_version.outputs.upstream_version }}" '
        '"${{ steps.check_version.outputs.package_revision }}"'
    )
    assert invocation in workflow


def test_scheduled_checks_gate_expensive_setup_early() -> None:
    workflow = WORKFLOW.read_text()
    assert "cron: '0 */4 * * *'" in workflow
    assert workflow.index("id: check_version") < workflow.index("name: Set up Python")
    assert "run_ci:" in workflow
    for expensive_step in (
        "name: Set up Python",
        "name: Install Python & Shell Linters",
        "name: Run static linters and format checks",
        "name: Run security audit via aurscan",
        "name: Run offline synthetic fixtures & breakage simulations",
    ):
        step_start = workflow.index(expensive_step)
        assert "if: steps.check_version.outputs.run_ci == 'true'" in workflow[step_start : step_start + 500]
    assert "Scheduled run found no upstream change; skipping validation and build." in workflow


def test_user_docs_keep_periodicity_abstract() -> None:
    readme = MODULE.README.read_text()
    publication = PUBLISH_WORKFLOW.read_text()
    assert "every few hours" in readme
    assert "every few hours" in publication
    assert "3× daily" not in readme
    assert "three times daily" not in publication


def test_release_build_instructions_are_in_maintainer_docs() -> None:
    readme = MODULE.README.read_text()
    verification = (MODULE.ROOT / "docs/verification.md").read_text()
    maintainer = MAINTAINER_DOC.read_text()
    command = "gh workflow run aur-sync.yml"
    assert command in maintainer
    assert command not in readme
    assert command not in verification


def test_local_build_uses_a_disposable_workspace() -> None:
    script = LOCAL_BUILD.read_text()
    assert 'mktemp -d' in script
    assert 'trap \'rm -rf "$build_dir"\' EXIT' in script
    assert 'makepkg "$@"' in script


def test_container_build_does_not_copy_package_archives_to_checkout() -> None:
    container = CONTAINER.read_text()
    assert 'build_dir="$(mktemp -d' in container
    assert 'trap \'rm -rf "$build_dir"\' EXIT' in container
    assert 'cp "$build_dir"/PKGBUILD "$build_dir"/.SRCINFO /github/workspace/' in container
    assert 'cp factory-ai-droid-cli-rnoz-bin-*.pkg.tar.zst PKGBUILD .SRCINFO /github/workspace/' not in container


def test_release_concurrency_and_failure_reporting_are_scoped() -> None:
    workflow = WORKFLOW.read_text()
    assert "format('factory-cli-pr-{0}', github.event.pull_request.number)" in workflow
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow
    assert "steps.check_version.outputs.run_ci == 'true'" in workflow
    assert "steps.check_version.outputs.should_build == 'true'" in workflow
    assert "needs.build-and-test.result == 'failure'" in workflow
    assert "UPSTREAM_VER: ${{ steps.check_version.outputs.upstream_version || 'unknown' }}" not in workflow
    assert "cc @rNoz — Manual inspection required." in workflow
    assert 'gh issue comment "$EXISTING_ISSUE"' in workflow
    build_block, report_block = workflow.split("  report-upstream-breakage:", 1)
    report_block = report_block.split("  publish:", 1)[0]
    assert "upstream_validation_failed:" in build_block
    assert "id: validate_upstream" in build_block
    assert "issues: write" not in build_block.split("  jobs:", 1)[-1].split("  publish:", 1)[0]
    assert "permissions:\n      contents: read\n      issues: write" in report_block
    assert "needs.build-and-test.outputs.upstream_validation_failed == 'true'" in report_block
    assert "|| true" not in report_block


def test_publication_uses_healed_metadata_without_dead_copy_paths() -> None:
    publication = PUBLISH_WORKFLOW.read_text()
    assert 'PACKAGE_VERSION="${UPSTREAM_VER}-${PKGREL}"' in publication
    assert "pkgver/pkgrel fields not found" in publication
    assert "git diff --quiet FETCH_HEAD HEAD -- PKGBUILD .SRCINFO" in publication
    assert "skipping AUR publish to avoid regressing AUR" in publication
    assert "if [ -f SRCINFO ]; then" not in publication


def test_reproducible_release_regeneration_is_documented() -> None:
    maintainer = MAINTAINER_DOC.read_text()
    command = "gh workflow run aur-sync.yml"
    assert command in maintainer
    assert "--repo rNoz/factory-ai-droid-cli-rnoz" in maintainer
    assert "-f upstream_version=X.Y.Z" in maintainer
    assert "-f package_revision=N" in maintainer
    assert "-f force_build=true" in maintainer
    assert "X.Y.Z-N" in maintainer
    assert "meaningful zero-diff PR" in maintainer
    assert "owner-only" in maintainer
    combined = " ".join(maintainer.lower().split())
    assert "future normal upstream releases use revision `1`" in combined
    assert "package changes increment the current revision" in combined


if __name__ == "__main__":
    test_upstream_detector_parses_first_semantic_ver()
    test_upstream_detector_rejects_missing_or_malformed_ver()
    test_upstream_detector_validates_owner_override()
    test_upstream_detector_cli_prints_owner_override()
    test_pkgver_can_be_set_for_release_metadata()
    test_standalone_metadata_update_synchronizes_all_version_fields()
    test_pkgrel_resets_when_upstream_version_changes()
    test_pkgrel_is_preserved_for_same_version_rebuilds()
    test_pkgrel_increments_for_same_version_package_rebuilds()
    test_pkgrel_can_be_set_for_release_metadata()
    test_srcinfo_revision_tracks_package_metadata()
    test_pkgbuild_checksums_match_packaged_sources()
    test_readme_has_single_license_section_and_nested_test_matrix()
    test_ci_badge_reflects_real_workflow_status()
    test_release_automation_uses_merge_gated_prs()
    test_upgrade_notice_reports_the_installed_version()
    test_metadata_agrees_on_version_and_revision()
    test_release_repair_guards_are_pinned()
    test_container_builds_the_calculated_package_revision()
    test_scheduled_checks_gate_expensive_setup_early()
    test_release_concurrency_and_failure_reporting_are_scoped()
    test_publication_uses_healed_metadata_without_dead_copy_paths()
    test_reproducible_release_regeneration_is_documented()
    print("ALL RELEASE METADATA TESTS PASSED")
