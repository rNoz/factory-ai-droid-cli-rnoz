#!/usr/bin/env python3
"""Update the tested-release matrix and version list after a release."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
VERSION_LIST = ROOT / "tests/test_versions.py"
README = ROOT / "README.md"


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def configured_versions() -> list[str]:
    match = re.search(r"VERSIONS_TO_TEST = \[\n(.*?)]", VERSION_LIST.read_text(), re.DOTALL)
    if not match:
        raise RuntimeError("VERSIONS_TO_TEST list not found")
    return sorted(
        set(re.findall(r'"([0-9]+\.[0-9]+\.[0-9]+)"', match.group(1))),
        key=version_key,
    )


def reset_pkgrel(text: str, current_version: str, new_version: str) -> str:
    if current_version == new_version:
        return text
    updated, count = re.subn(r"^pkgrel=\d+$", "pkgrel=1", text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError("pkgrel field not found")
    return updated


def reset_pkgrel_if_version_changed(version: str) -> None:
    text = PKGBUILD.read_text()
    match = re.search(r"^pkgver=(.+)$", text, re.MULTILINE)
    if not match:
        raise RuntimeError("pkgver field not found")
    updated = reset_pkgrel(text, match.group(1), version)
    if updated != text:
        PKGBUILD.write_text(updated)


def update_version_list(version: str) -> None:
    text = VERSION_LIST.read_text()
    versions = configured_versions()
    if version in versions:
        return
    match = re.search(r"(VERSIONS_TO_TEST = \[\n)(.*?)(\n\])", text, re.DOTALL)
    if not match:
        raise RuntimeError("VERSIONS_TO_TEST list not found")
    versions.append(version)
    replacement = match.group(1) + "".join(f'    "{item}",\n' for item in sorted(set(versions), key=version_key))
    VERSION_LIST.write_text(text[: match.start()] + replacement + "]" + text[match.end() :])


def badge(version: str, architecture: str, color: str) -> str:
    label = f"{version}-{architecture}".replace(" ", "%20")
    url = "https://github.com/rNoz/factory-ai-droid-cli-rnoz/actions/workflows/aur-sync.yml"
    return f"[![{version} {architecture}](https://img.shields.io/badge/{label}-{color})]({url})"


def update_readme(version: str) -> None:
    text = README.read_text()
    table_start = text.index("| linux x86_64 avx2 | linux x86_64 |")
    table_end = text.find("\n\n", table_start)
    if table_end == -1:
        raise RuntimeError("tested-release table terminator not found")
    versions = configured_versions()
    table = "\n".join(
        ["| linux x86_64 avx2 | linux x86_64 |", "| :-- | :-- |"]
        + [
            f"| {badge(item, 'x64 AVX2', 'brightgreen')} | "
            f"{badge(item, 'x64 baseline', 'brightgreen')} |"
            for item in versions
        ]
    )
    text = text[:table_start] + table + text[table_end:]
    text = re.sub(r"tested%20releases-[0-9]+%20", f"tested%20releases-{len(versions)}%20", text, count=1)
    README.write_text(text)


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", sys.argv[1]):
        print(f"usage: {Path(sys.argv[0]).name} VERSION", file=sys.stderr)
        return 2
    version = sys.argv[1]
    reset_pkgrel_if_version_changed(version)
    update_version_list(version)
    update_readme(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
