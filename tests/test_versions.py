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

# Test releases covering major engine and minification changes
VERSIONS_TO_TEST = [
    "0.200.0",
    "0.205.0",
    "0.210.0",
    "0.211.0",
    "0.213.0",
    "0.215.0",
    "0.215.1",
]

BASE_URL = "https://downloads.factory.ai/factory-cli/releases"

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

    return True


ARCH_VARIANTS = ["x64", "x64-baseline"]


def test_variant(ver: str, arch: str) -> bool:
    url = f"{BASE_URL}/{ver}/linux/{arch}/droid"
    # The JS bundle is packed into the tail ~60MB of the binary
    headers = {"Range": "bytes=-60000000"}
    req = urllib.request.Request(url, headers=headers)

    data = None
    last_err = None
    retries = 3
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
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

    print(
        f"  [PASS] v{ver} ({arch}): match len={match_len} bytes, "
        f"code={matched_bytes.decode('utf-8', errors='replace')}"
    )
    return True


def test_version(ver: str) -> bool:
    print(f"Testing release v{ver} (both AVX2 and baseline)...")
    for arch in ARCH_VARIANTS:
        if not test_variant(ver, arch):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-version and synthetic test suite for Droid patcher")
    parser.add_argument("--offline", action="store_true", help="Run only offline synthetic fixture tests")
    parser.add_argument("versions", nargs="*", help="Optional specific version(s) to test")
    args = parser.parse_args()

    if not test_synthetic_fixtures():
        print("SYNTHETIC FIXTURE TESTS FAILED.")
        return 1
    print("ALL SYNTHETIC FIXTURE TESTS PASSED.\n")

    if args.offline:
        return 0

    versions = args.versions if args.versions else VERSIONS_TO_TEST
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
