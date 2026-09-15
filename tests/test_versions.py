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
    "0.216.0",
    "0.217.0",
    "0.218.0",
    "0.218.1",
    "0.218.2",
    "0.219.0",
]

BASE_URL = "https://downloads.factory.ai/factory-cli/releases"
LATEST_VERSION_URL = "https://app.factory.ai/cli"
# Fallback middle window measured against the 100-180 MB keymap/runtime span
# in v0.219.0 and the historical 302-310 MB releases.
KEYBINDING_RANGE_START = 100000000
KEYBINDING_RANGE_END = 180000000
KEYBINDING_RANGE = f"bytes={KEYBINDING_RANGE_START}-{KEYBINDING_RANGE_END}"

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
RANGE_RESPONSE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+)$")


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


def merge_range_data(
    first_data: bytes, first_start: int, second_data: bytes, second_start: int
) -> bytes:
    """Join ordered byte ranges without duplicating overlap or bridging gaps."""
    if patch_keybindings.RANGE_GAP in first_data or patch_keybindings.RANGE_GAP in second_data:
        raise ValueError("range data contains the reserved gap marker")
    first_end = first_start + len(first_data)
    second_end = second_start + len(second_data)
    if first_start <= second_start:
        if first_end < second_start:
            return first_data + patch_keybindings.RANGE_GAP + second_data
        overlap_end = min(first_end, second_end)
        overlap = max(0, overlap_end - second_start)
        first_overlap_start = second_start - first_start
        if overlap and first_data[first_overlap_start : first_overlap_start + overlap] != second_data[:overlap]:
            raise ValueError("overlapping byte ranges changed between requests")
        return first_data + second_data[overlap:]
    if second_end < first_start:
        return second_data + patch_keybindings.RANGE_GAP + first_data
    overlap_end = min(second_end, first_end)
    overlap = max(0, overlap_end - first_start)
    second_overlap_start = first_start - second_start
    if overlap and second_data[second_overlap_start : second_overlap_start + overlap] != first_data[:overlap]:
        raise ValueError("overlapping byte ranges changed between requests")
    return second_data + first_data[overlap:]


def _validate_range_response(
    data: bytes, status: int, content_range: str, content_length: str
) -> None:
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise ValueError("range response has an invalid Content-Length") from error
        if declared_length != len(data):
            raise ValueError("range response body length disagrees with Content-Length")
    if status == 200:
        if content_range:
            raise ValueError("full range response unexpectedly included Content-Range")
        return
    if status != 206:
        raise ValueError(f"range request returned unexpected HTTP status {status}")
    match = RANGE_RESPONSE_RE.fullmatch(content_range)
    if not match:
        raise ValueError("partial range response is missing a valid Content-Range")
    start, end, total = (int(value) for value in match.groups())
    if end < start or total <= end or len(data) != end - start + 1:
        raise ValueError("partial range response has inconsistent bounds or body length")


def fetch_range(url: str, range_header: str, retries: int = 3) -> tuple[bytes, str, int]:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"Range": range_header})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                content_range = resp.headers.get("Content-Range") or ""
                status = int(getattr(resp, "status", None) or resp.getcode())
                _validate_range_response(
                    data,
                    status,
                    content_range,
                    resp.headers.get("Content-Length") or "",
                )
                return data, content_range, status
        except Exception as err:
            last_err = err
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"range request failed after {retries} attempts: {last_err}")


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

    if merge_range_data(b"EFGHIJ", 4, b"IJKLMN", 8) != b"EFGHIJKLMN":
        print("  [FAIL] Synthetic fixture: overlapping ranges were not merged uniquely")
        return False
    if merge_range_data(b"EF", 4, b"YZ", 10) != b"EF" + patch_keybindings.RANGE_GAP + b"YZ":
        print("  [FAIL] Synthetic fixture: disjoint ranges were joined without a guard")
        return False
    if merge_range_data(b"0123456789", 0, b"234", 2) != b"0123456789":
        print("  [FAIL] Synthetic fixture: nested range was not merged")
        return False
    if merge_range_data(b"234", 2, b"0123456789", 0) != b"0123456789":
        print("  [FAIL] Synthetic fixture: reverse nested range was not merged")
        return False
    _validate_range_response(b"ABCD", 206, "bytes 10-13/20", "4")
    _validate_range_response(b"ABCD", 200, "", "4")
    for response in (
        (b"ABC", 206, "bytes 10-13/20", "3"),
        (b"ABCD", 206, "", "4"),
        (b"ABCD", 200, "bytes 0-3/4", "4"),
        (b"ABCD", 500, "", "4"),
    ):
        try:
            _validate_range_response(*response)
        except ValueError:
            continue
        print("  [FAIL] Synthetic fixture: malformed range response was accepted")
        return False
    print("  [PASS] Synthetic fixture: range overlap and gap handling are fail-safe")

    return True


ARCH_VARIANTS = ["x64", "x64-baseline"]


def test_variant(ver: str, arch: str) -> bool:
    url = f"{BASE_URL}/{ver}/linux/{arch}/droid"
    # The JS bundle is packed into the tail ~60MB of the binary
    data = b""
    tail_start: int | None = None
    total_size: int | None = None
    try:
        data, content_range, response_status = fetch_range(url, "bytes=-60000000")
    except RuntimeError as error:
        print(f"  [FAIL] Network or range request failed for v{ver} ({arch}): {error}")
        return False
    if response_status == 200:
        tail_start = 0
        total_size = len(data)
    else:
        range_match = RANGE_RESPONSE_RE.fullmatch(content_range)
        if not range_match:
            print(f"  [FAIL] Invalid range response for v{ver} ({arch})")
            return False
        tail_start = int(range_match.group(1))
        total_size = int(range_match.group(3))

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
        # The runtime handler and serialized keymap can move independently
        # between releases. Use one contiguous window so duplicate overlapping
        # ranges cannot create false ambiguity during cross-validation.
        mid_range = KEYBINDING_RANGE
        try:
            extra_data, extra_range, extra_status = fetch_range(url, mid_range)
            if extra_status == 200:
                if total_size is not None and len(extra_data) != total_size:
                    raise ValueError("full fallback response length disagrees with tail range")
                keybinding_data = extra_data
            else:
                extra_match = RANGE_RESPONSE_RE.fullmatch(extra_range)
                if not extra_match:
                    raise ValueError("fallback range response is missing a valid Content-Range")
                extra_start = int(extra_match.group(1))
                extra_total_size = int(extra_match.group(3))
                if total_size is not None and extra_total_size != total_size:
                    raise ValueError("range responses reported different total sizes")
                total_size = extra_total_size
                if len(data) == total_size:
                    keybinding_data = data
                else:
                    if tail_start is None:
                        tail_start = total_size - len(data)
                    keybinding_data = merge_range_data(extra_data, extra_start, data, tail_start)
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
