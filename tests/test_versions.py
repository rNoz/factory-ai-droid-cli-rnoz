#!/usr/bin/env python3
"""Multi-version test suite and synthetic fixture tests for Droid binary patcher.

Validates that the patcher successfully identifies, verifies, and generates
byte-exact zero-drift replacements across a wide range of historical and
current Factory Droid releases, as well as offline synthetic test fixtures.
"""

import argparse
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "patches"))
import patch_keybindings  # noqa: E402

# Test releases covering major engine and minification changes
VERSIONS_TO_TEST = [
    "0.200.0",
    "0.205.0",
    "0.210.0",
    "0.211.0",
    "0.213.0",
    "0.215.0",
    "0.215.1",
    "0.217.0",
]

BASE_URL = "https://downloads.factory.ai/factory-cli/releases"
LATEST_VERSION_URL = "https://app.factory.ai/cli"
# Fallback middle window for the keymap search when the server omits
# Content-Range; the primary path derives the window from the binary size.
KEYBINDING_RANGE = "bytes=100000000-180000000"

# The serialized keymap table, guarded dispatch statements, and model registry
# first appear between 0.200.0 and 0.205.0: byte probes of the complete
# v0.200.0 span (154.6 MB) find no ctrl-g\x00, model-cycle, or autonomy-cycle
# strings at all, while v0.205.0 carries all of them. Releases before the
# floor are validated title-only; the rotation patcher itself still fails
# closed on them.
KEYBINDING_FLOOR = "0.205.0"


def version_key(ver: str) -> tuple[int, ...]:
    return tuple(int(part) for part in ver.split("."))


def keybinding_expected(ver: str) -> bool:
    return version_key(ver) >= version_key(KEYBINDING_FLOOR)


PRIMARY_PATTERN = re.compile(rb"if\(([a-zA-Z0-9_$.()]+\.isNonInteractiveCLIMode\(\))\)return null;")
CONTEXT_MARKERS = [b"formatTitle", b"isSessionTitleManuallySet", b"firstUserText"]


def find_valid_matches(data: bytes):
    matches = list(PRIMARY_PATTERN.finditer(data))
    valid = []
    for m in matches:
        start = m.start()
        end = m.end()
        window = data[max(0, start - 300) : min(len(data), end + 300)]
        if any(marker in window for marker in CONTEXT_MARKERS):
            valid.append(m)
    return valid


def compute_replacement(matched_bytes: bytes) -> bytes:
    match_len = len(matched_bytes)
    prefix = b"if(true)return null;/*"
    suffix = b"*/"
    padding = b" " * (match_len - len(prefix) - len(suffix))
    replacement = prefix + padding + suffix
    return replacement


def test_synthetic_fixtures() -> bool:
    print("Running offline synthetic fixture tests...")

    # 1. Valid contextual guard
    sample_valid = (
        b"function generateTitle(){let firstUserText='hi';"
        b"if(this.flags.isNonInteractiveCLIMode())return null;"
        b"return formatTitle(res);}"
    )
    valid_matches = find_valid_matches(sample_valid)
    if len(valid_matches) != 1:
        print("  [FAIL] Synthetic valid fixture: expected 1 match, got", len(valid_matches))
        return False
    rep = compute_replacement(valid_matches[0].group(0))
    if len(rep) != len(valid_matches[0].group(0)):
        print("  [FAIL] Synthetic valid fixture: length mismatch")
        return False
    if not (rep.startswith(b"if(true)return null;/*") and rep.endswith(b"*/")):
        print("  [FAIL] Synthetic valid fixture: invalid comment framing")
        return False
    print("  [PASS] Synthetic fixture: contextual single match and length preservation")

    # 2. Guard present without context markers (must reject)
    sample_no_context = (
        b"function unrelatedWork(){let x=1;"
        b"if(this.flags.isNonInteractiveCLIMode())return null;"
        b"return doOtherThings();}"
    )
    if len(find_valid_matches(sample_no_context)) != 0:
        print("  [FAIL] Synthetic fixture: guard without context markers was not rejected")
        return False
    print("  [PASS] Synthetic fixture: uncontextual guard correctly ignored")

    # 3. Duplicate contextual guards (must reject as ambiguous)
    sample_duplicate = (
        b"function generateTitle(){let firstUserText='hi';"
        b"if(this.flags.isNonInteractiveCLIMode())return null;"
        b"if(this.flags.isNonInteractiveCLIMode())return null;"
        b"return formatTitle(res);}"
    )
    if len(find_valid_matches(sample_duplicate)) != 2:
        print("  [FAIL] Synthetic fixture: duplicate detection unexpected count")
        return False
    print("  [PASS] Synthetic fixture: duplicate contextual guards identified for fail-safe rejection")

    # 4. Zero matches
    sample_empty = b"function cleanCode(){ return 42; }"
    if len(find_valid_matches(sample_empty)) != 0:
        print("  [FAIL] Synthetic fixture: empty match test failed")
        return False
    print("  [PASS] Synthetic fixture: zero-match correctly returns no match")

    # 5. Keybinding gate: releases that predate the interactive keymap must be
    # validated title-only instead of failing on the rotation patcher.
    if keybinding_expected("0.200.0"):
        print("  [FAIL] Synthetic fixture: pre-floor release wrongly demands keybinding rotation")
        return False
    if not (keybinding_expected("0.205.0") and keybinding_expected("0.216.0")):
        print("  [FAIL] Synthetic fixture: keymap-era release wrongly skips keybinding rotation")
        return False
    if not (keybinding_expected("0.204.9") is False and keybinding_expected("0.205.0") is True):
        print("  [FAIL] Synthetic fixture: keybinding floor boundary is not exact")
        return False
    print("  [PASS] Synthetic fixture: keybinding floor gates only pre-keymap releases")

    return True


ARCH_VARIANTS = ["x64", "x64-baseline"]


def test_variant(ver: str, arch: str) -> bool:
    url = f"{BASE_URL}/{ver}/linux/{arch}/droid"
    # The JS bundle is packed into the tail ~60MB of the binary
    headers = {"Range": "bytes=-60000000"}
    req = urllib.request.Request(url, headers=headers)

    data = None
    total_size = 0
    last_err = None
    retries = 3
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                content_range = resp.headers.get("Content-Range") or ""
                if "/" in content_range:
                    total_size = int(content_range.rsplit("/", 1)[-1])
            break
        except Exception as err:
            last_err = err
            if attempt < retries:
                time.sleep(1.5 * attempt)

    if data is None:
        print(f"  [FAIL] Network or range request failed after {retries} attempts for v{ver} ({arch}): {last_err}")
        return False

    valid_matches = find_valid_matches(data)
    if len(valid_matches) != 1:
        print(f"  [FAIL] Expected exactly 1 contextual match for v{ver} ({arch}), found {len(valid_matches)}")
        return False

    match = valid_matches[0]
    matched_bytes = match.group(0)
    match_len = len(matched_bytes)

    replacement = compute_replacement(matched_bytes)
    assert len(replacement) == match_len, f"Length mismatch: {len(replacement)} != {match_len}"
    assert replacement.startswith(b"if(true)return null;/*")
    assert replacement.endswith(b"*/")

    if not keybinding_expected(ver):
        print(
            f"  [PASS] v{ver} ({arch}): match len={match_len} bytes, "
            f"title={matched_bytes.decode('utf-8', errors='replace')}; "
            f"keybindings=skipped (predates interactive keymap)"
        )
        return True

    try:
        patched_keybindings = patch_keybindings.apply_patch_bytes(data)
    except patch_keybindings.PatchError:
        # The runtime handler is in the tail, while the serialized keymap/help
        # resources sit at ~42% of binary size (measured: 42.1% in v0.205.0,
        # 42.2% in v0.215.1) and so can live earlier in large binaries. Derive
        # that middle window from the total size reported by the tail request.
        if total_size:
            mid_range = f"bytes={max(0, int(total_size * 0.25))}-{int(total_size * 0.60)}"
        else:
            mid_range = KEYBINDING_RANGE
        extra_req = urllib.request.Request(url, headers={"Range": mid_range})
        try:
            with urllib.request.urlopen(extra_req, timeout=30) as resp:
                keybinding_data = data + resp.read()
            patched_keybindings = patch_keybindings.apply_patch_bytes(keybinding_data)
        except Exception as error:
            print(f"  [FAIL] Keybinding patch rejected v{ver} ({arch}): {error}")
            return False
    else:
        keybinding_data = data
    if len(patched_keybindings) != len(keybinding_data):
        print(f"  [FAIL] Keybinding patch changed binary size for v{ver} ({arch})")
        return False
    if patched_keybindings == keybinding_data:
        print(f"  [FAIL] Keybinding patch made no change for v{ver} ({arch})")
        return False
    if patch_keybindings.apply_patch_bytes(patched_keybindings) != patched_keybindings:
        print(f"  [FAIL] Keybinding patch is not idempotent for v{ver} ({arch})")
        return False

    # The rotation is a byte-level remap on human chord styles: old queue
    # hints (G) move to Q, old model hints (N) to P, and old editor hints (P)
    # to G, in every style ("Ctrl+P", "Ctrl + P", "ctrl+N", ...).
    for template in (b"Ctrl+%s", b"Ctrl + %s", b"ctrl+%s", b"Ctrl-%s"):
        before = {
            letter: keybinding_data.count(template % letter)
            for letter in (b"G", b"N", b"P", b"Q")
        }
        after = {
            letter: patched_keybindings.count(template % letter)
            for letter in (b"G", b"N", b"P", b"Q")
        }
        expected = {b"G": before[b"P"], b"N": 0, b"P": before[b"N"], b"Q": before[b"G"]}
        if after != expected:
            print(f"  [FAIL] Chord display counts did not rotate ({template!r}) for v{ver} ({arch})")
            return False

    print(
        f"  [PASS] v{ver} ({arch}): match len={match_len} bytes, "
        f"title={matched_bytes.decode('utf-8', errors='replace')}; keybindings=patched"
    )
    return True


def fetch_latest_version() -> str:
    req = urllib.request.Request(LATEST_VERSION_URL)
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read().decode("utf-8")
    match = re.search(r'VER="([0-9]+\.[0-9]+\.[0-9]+)"', content)
    if not match:
        raise RuntimeError("upstream version endpoint did not contain a semantic version")
    return match.group(1)


def test_version(ver: str) -> bool:
    print(f"Testing release v{ver} (both AVX2 and baseline)...")
    for arch in ARCH_VARIANTS:
        if not test_variant(ver, arch):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-version and synthetic test suite for Droid patcher")
    parser.add_argument("--offline", action="store_true", help="Run only offline synthetic fixture tests")
    parser.add_argument("--latest", action="store_true", help="Fetch and include the latest upstream release")
    parser.add_argument("versions", nargs="*", help="Optional specific version(s) to test")
    args = parser.parse_args()

    if not test_synthetic_fixtures():
        print("SYNTHETIC FIXTURE TESTS FAILED.")
        return 1
    print("ALL SYNTHETIC FIXTURE TESTS PASSED.\n")

    if args.offline:
        return 0

    versions = args.versions if args.versions else VERSIONS_TO_TEST
    if args.latest:
        latest = fetch_latest_version()
        if latest not in versions:
            versions = [latest, *versions]
        print(f"Including latest upstream release: {latest}")
    print(f"Running multi-version validation across {len(versions)} releases ({', '.join(ARCH_VARIANTS)})...")
    failed = 0
    for v in versions:
        if not test_version(v):
            failed += 1

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"ALL {len(versions)} RELEASES PASSED VALIDATION.")
        return 0
    else:
        print(f"{failed}/{len(versions)} RELEASES FAILED VALIDATION.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
