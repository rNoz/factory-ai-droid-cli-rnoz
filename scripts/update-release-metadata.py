#!/usr/bin/env python3
"""Update the tested-release matrix and version list after a release."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
VERSION_LIST = ROOT / "tests/test_versions.py"
README = ROOT / "README.md"
PKGBUILD = ROOT / "PKGBUILD"


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


def bump_pkgrel(text: str) -> str:
    match = re.search(r"^pkgrel=(\d+)$", text, re.MULTILINE)
    if not match:
        raise RuntimeError("pkgrel field not found")
    next_pkgrel = int(match.group(1)) + 1
    return text[: match.start()] + f"pkgrel={next_pkgrel}" + text[match.end() :]


def set_pkgrel(text: str, pkgrel: int) -> str:
    if pkgrel < 1:
        raise ValueError("pkgrel must be at least 1")
    updated, count = re.subn(r"^pkgrel=\d+$", f"pkgrel={pkgrel}", text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError("pkgrel field not found")
    return updated


def set_pkgver(text: str, version: str) -> str:
    updated, count = re.subn(r"^pkgver=.*$", f"pkgver={version}", text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError("pkgver field not found")
    return updated


def update_srcinfo(text: str, version: str, pkgrel: int) -> str:
    updated, version_count = re.subn(
        r"^(\s*pkgver = ).*$", rf"\g<1>{version}", text, count=1, flags=re.MULTILINE
    )
    updated, pkgrel_count = re.subn(
        r"^(\s*pkgrel = ).*$", rf"\g<1>{pkgrel}", updated, count=1, flags=re.MULTILINE
    )
    if version_count != 1 or pkgrel_count != 1:
        raise RuntimeError("pkgver/pkgrel fields not found in .SRCINFO")
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
    return (
        f'<a href="{url}">'
        f'<img src="https://img.shields.io/badge/{label}-{color}" alt="{version} {architecture}" />'
        f"</a>"
    )


def update_readme(version: str, pkgrel: int) -> None:
    text = README.read_text()
    start_marker = "<!-- tested-releases:start -->"
    end_marker = "<!-- tested-releases:end -->"
    # GitHub renders tables as display:block, so only a raw HTML table with
    # align="center" actually centers; markdown tables ignore ancestor text-align.
    table_start = text.index(start_marker) + len(start_marker)
    table_end = text.index(end_marker)
    versions = configured_versions()
    rows = "\n".join(
        f'    <tr><td>{badge(item, "x64 AVX2", "brightgreen")}</td>'
        f'<td>{badge(item, "x64 baseline", "brightgreen")}</td></tr>'
        for item in versions
    )
    table = (
        '\n<table align="center">\n'
        "  <thead>\n"
        "    <tr><th>linux x86_64 avx2</th><th>linux x86_64</th></tr>\n"
        "  </thead>\n"
        "  <tbody>\n"
        f"{rows}\n"
        "  </tbody>\n"
        "</table>\n"
    )
    text = text[:table_start] + table + text[table_end:]
    text = re.sub(r"tested%20releases-[0-9]+", f"tested%20releases-{len(versions)}", text, count=1)
    README.write_text(text)


def main() -> int:
    if len(sys.argv) not in (2, 3, 4) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", sys.argv[1]):
        print(f"usage: {Path(sys.argv[0]).name} VERSION [--bump-pkgrel|--set-pkgrel N]", file=sys.stderr)
        return 2
    version = sys.argv[1]
    if len(sys.argv) == 3 and sys.argv[2] != "--bump-pkgrel":
        print(f"usage: {Path(sys.argv[0]).name} VERSION [--bump-pkgrel|--set-pkgrel N]", file=sys.stderr)
        return 2
    if len(sys.argv) == 4 and (
        sys.argv[2] != "--set-pkgrel" or not sys.argv[3].isdigit() or int(sys.argv[3]) < 1
    ):
        print(f"usage: {Path(sys.argv[0]).name} VERSION [--bump-pkgrel|--set-pkgrel N]", file=sys.stderr)
        return 2
    text = PKGBUILD.read_text()
    current_version = re.search(r"^pkgver=(.+)$", text, re.MULTILINE)
    if not current_version:
        raise RuntimeError("pkgver field not found")
    updated = set_pkgver(text, version)
    updated = reset_pkgrel(updated, current_version.group(1), version)
    if len(sys.argv) == 3 and current_version.group(1) == version:
        updated = bump_pkgrel(updated)
    if len(sys.argv) == 4:
        updated = set_pkgrel(updated, int(sys.argv[3]))
    if updated != text:
        PKGBUILD.write_text(updated)
    pkgrel_match = re.search(r"^pkgrel=(\d+)$", updated, re.MULTILINE)
    if not pkgrel_match:
        raise RuntimeError("pkgrel field not found")
    pkgrel = int(pkgrel_match.group(1))
    srcinfo_path = ROOT / ".SRCINFO"
    if not srcinfo_path.is_file():
        raise RuntimeError(".SRCINFO file not found")
    srcinfo_path.write_text(update_srcinfo(srcinfo_path.read_text(), version, pkgrel))
    update_version_list(version)
    update_readme(version, pkgrel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
