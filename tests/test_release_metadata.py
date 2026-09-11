#!/usr/bin/env python3

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/update-release-metadata.py"
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


if __name__ == "__main__":
    test_pkgrel_resets_when_upstream_version_changes()
    test_pkgrel_is_preserved_for_same_version_rebuilds()
    test_readme_has_single_license_section_and_nested_test_matrix()
    test_ci_badge_uses_shields_endpoint()
    print("ALL RELEASE METADATA TESTS PASSED")
