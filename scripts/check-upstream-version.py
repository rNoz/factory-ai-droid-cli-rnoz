#!/usr/bin/env python3
"""Print the current or owner-requested upstream Factory CLI version."""

import argparse
import re
import sys
import urllib.request


UPSTREAM_URL = "https://app.factory.ai/cli"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def validate_version(version: str) -> str:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"invalid semantic version: {version!r}")
    return version


def parse_version(text: str) -> str:
    match = re.search(r'VER="([^"]+)"', text)
    if not match:
        raise ValueError('upstream response does not contain VER="X.Y.Z"')
    return validate_version(match.group(1))


def fetch_version() -> str:
    request = urllib.request.Request(UPSTREAM_URL, headers={"User-Agent": "factory-ai-droid-cli-rnoz"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return parse_version(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--override", help="use an owner-selected semantic version")
    args = parser.parse_args()
    try:
        version = validate_version(args.override) if args.override else fetch_version()
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
