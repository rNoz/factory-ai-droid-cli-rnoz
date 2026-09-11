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


def update_version_list(version: str) -> None:
    text = VERSION_LIST.read_text()
    if f'"{version}"' in text:
        return
    match = re.search(r"(VERSIONS_TO_TEST = \[\n)(.*?)(\n\])", text, re.DOTALL)
    if not match:
        raise RuntimeError("VERSIONS_TO_TEST list not found")
    versions = re.findall(r'"([0-9]+\.[0-9]+\.[0-9]+)"', match.group(2))
    versions.append(version)
    replacement = match.group(1) + "".join(f'    "{item}",\n' for item in sorted(set(versions), key=version_key))
    VERSION_LIST.write_text(text[: match.start()] + replacement + "]" + text[match.end() :])


def badge(version: str, architecture: str, color: str) -> str:
    label = f"{version} {architecture}".replace(" ", "%20")
    url = "https://github.com/rNoz/factory-ai-droid-cli-rnoz/actions/workflows/aur-sync.yml"
    return f"[![{version} {architecture}](https://img.shields.io/badge/{label}-{color})]({url})"


def update_readme(version: str) -> None:
    text = README.read_text()
    table_start = text.index("| Release | x64 AVX2 | x64 baseline |")
    table_end = text.find("\n\n", table_start)
    if table_end == -1:
        raise RuntimeError("tested-release table terminator not found")
    rows = {}
    for row in text[table_start:table_end].splitlines()[2:]:
        match = re.match(r"\| ([0-9]+\.[0-9]+\.[0-9]+) \|", row)
        if match:
            rows[match.group(1)] = row
    rows[version] = (
        f"| {version} | {badge(version, 'x64 AVX2', 'brightgreen')} | "
        f"{badge(version, 'x64 baseline', 'brightgreen')} |"
    )
    table = "\n".join(
        ["| Release | x64 AVX2 | x64 baseline |", "| :-- | :-- | :-- |"]
        + [rows[item] for item in sorted(rows, key=version_key)]
    )
    text = text[:table_start] + table + text[table_end:]
    text = re.sub(r"tested%20releases-[0-9]+%20", f"tested%20releases-{len(rows)}%20", text, count=1)
    README.write_text(text)


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", sys.argv[1]):
        print(f"usage: {Path(sys.argv[0]).name} VERSION", file=sys.stderr)
        return 2
    version = sys.argv[1]
    update_version_list(version)
    update_readme(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
