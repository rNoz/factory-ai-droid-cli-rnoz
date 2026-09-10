#!/usr/bin/env python3
"""Fetch and extract version release notes from official Factory AI changelog."""

import re
import sys
import urllib.request


def fetch_changelog(version: str) -> str:
    url = "https://docs.factory.ai/changelog/release-notes.md"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "factory-ai-droid-cli-rnoz-packager"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")

        # 1. Try exact version match
        pattern = rf"(## CLI v{re.escape(version)}[^\n]*\n.*?\n)(?=\n## |\Z)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 2. Try base minor version if patch version (e.g., 0.215.0 for 0.215.1)
        parts = version.split(".")
        if len(parts) == 3 and parts[2] != "0":
            base_ver = f"{parts[0]}.{parts[1]}.0"
            pattern_base = rf"(## CLI v{re.escape(base_ver)}[^\n]*\n.*?\n)(?=\n## |\Z)"
            match_base = re.search(pattern_base, content, re.DOTALL)
            if match_base:
                return (
                    f"> Note: Upstream release notes for patch `{version}` are based on `{base_ver}` series.\n\n"
                    + match_base.group(1).strip()
                )

        # 3. Handle upstream docs changelog lagging behind binary releases
        latest_match = re.search(r"## CLI v([0-9]+\.[0-9]+\.[0-9]+)[^\n]*\n", content)
        if latest_match:
            latest_doc_ver = latest_match.group(1)
            msg = (
                f"> **Notice**: Upstream binary release `v{version}` has been published to `app.factory.ai/cli`,\n"
                f"> but official documentation notes currently lag behind (latest entry: `v{latest_doc_ver}`).\n\n"
                f"Refer to the [Official Factory Release Notes](https://docs.factory.ai/changelog/release-notes)\n"
                f"([Raw Markdown](https://docs.factory.ai/changelog/release-notes.md)) for doc updates."
            )
            return msg

    except Exception as err:
        return f"> Could not automatically fetch upstream changelog: {err}"

    msg = (
        f"> Upstream release notes for `v{version}` have not been published yet in the changelog.\n"
        f"> See [Official Factory Release Notes](https://docs.factory.ai/changelog/release-notes)."
    )
    return msg


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else "0.215.1"
    version = version.lstrip("v")
    notes = fetch_changelog(version)
    print(notes)


if __name__ == "__main__":
    main()
