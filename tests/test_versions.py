#!/usr/bin/env python3
"""Multi-version test suite and synthetic fixture tests for Droid binary patcher.

Validates that the patcher successfully identifies, verifies, and generates
byte-exact zero-drift replacements across a wide range of historical and
current Factory Droid releases, as well as offline synthetic test fixtures.
"""

import argparse
import json
import re
import struct
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "patches"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
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
    "0.220.0",
    "0.221.0",
    "0.222.0",
    "0.223.0",
    "0.224.0",
    "0.224.1",
    "0.225.0",
]

BASE_URL = "https://downloads.factory.ai/factory-cli/releases"
LATEST_VERSION_URL = "https://app.factory.ai/cli"
RELEASE_WINDOWS_FILE = Path(__file__).resolve().parent / "release_windows.json"
RELEASE_WINDOWS: dict[str, dict] = (
    json.loads(RELEASE_WINDOWS_FILE.read_text())
    if RELEASE_WINDOWS_FILE.exists()
    else {}
)

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


def assemble_range_windows(windows: list[tuple[int, bytes]]) -> bytes:
    """Join ordered byte windows, inserting RANGE_GAP only for true holes."""
    if not windows:
        raise ValueError("no byte windows to assemble")
    ordered = sorted(windows, key=lambda item: item[0])
    cursor_start, assembled = ordered[0]
    cursor_end = cursor_start + len(assembled)
    segment_base = 0
    for start, blob in ordered[1:]:
        end = start + len(blob)
        if start > cursor_end:
            assembled += patch_keybindings.RANGE_GAP + blob
            segment_base = len(assembled) - len(blob)
            cursor_start, cursor_end = start, end
            continue
        if end <= cursor_end:
            overlap_off = segment_base + (start - cursor_start)
            if assembled[overlap_off : overlap_off + len(blob)] != blob:
                raise ValueError("overlapping byte ranges changed between requests")
            continue
        overlap = cursor_end - start
        if overlap and assembled[-overlap:] != blob[:overlap]:
            raise ValueError("overlapping byte ranges changed between requests")
        assembled += blob[max(overlap, 0) :]
        cursor_end = end
    return assembled


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
    three = assemble_range_windows([(4, b"EF"), (10, b"YZ"), (20, b"AB")])
    expected_three = b"EF" + patch_keybindings.RANGE_GAP + b"YZ" + patch_keybindings.RANGE_GAP + b"AB"
    if three != expected_three:
        print("  [FAIL] Synthetic fixture: three disjoint windows were not assembled")
        return False
    if assemble_range_windows([(0, b"0123456789"), (2, b"234"), (8, b"89")]) != b"0123456789":
        print("  [FAIL] Synthetic fixture: overlapping window set was not assembled")
        return False
    try:
        nested_after_gap = assemble_range_windows(
            [(0, b"AAAA"), (10, b"BBBB"), (12, b"BB")]
        )
    except ValueError:
        print("  [FAIL] Synthetic fixture: contained window after a gap was rejected")
        return False
    if nested_after_gap != b"AAAA" + patch_keybindings.RANGE_GAP + b"BBBB":
        print("  [FAIL] Synthetic fixture: contained window after a gap was assembled wrong")
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

    # 6. Title guard lives before the last-60MB tail. The last-60MB slice
    # must not invent a match, and title-window discovery must recover the
    # unique contextual guard without loosening the pattern.
    guard = (
        b"function generateTitle(){let firstUserText='hi';"
        b"if(Ue().isNonInteractiveCLIMode())return null;"
        b"return formatTitle(res);}"
    )
    guard_at = 1_048_576
    tail_start = 70_000_000
    total_size = tail_start + 1_000
    tail_slice = b"\x00" * 1_000
    if find_valid_matches(tail_slice):
        print("  [FAIL] Synthetic fixture: empty tail slice produced a title match")
        return False

    original_fetch_range = fetch_range

    def fake_fetch_range(url: str, range_header: str, retries: int = 3):
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
        if not match:
            raise ValueError(f"unexpected range header: {range_header}")
        start, end = int(match.group(1)), int(match.group(2))
        length = end - start + 1
        blob = bytearray(length)
        guard_end = guard_at + len(guard)
        overlap_start = max(start, guard_at)
        overlap_end = min(end + 1, guard_end)
        if overlap_start < overlap_end:
            src = overlap_start - guard_at
            dst = overlap_start - start
            span = overlap_end - overlap_start
            blob[dst : dst + span] = guard[src : src + span]
        return bytes(blob), f"bytes {start}-{end}/{total_size}", 206

    try:
        globals()["fetch_range"] = fake_fetch_range
        discovered = discover_title_window("https://example.invalid/droid", total_size, tail_start)
    finally:
        globals()["fetch_range"] = original_fetch_range

    if discovered is None:
        print("  [FAIL] Synthetic fixture: title window before tail was not discovered")
        return False
    window_start, window_len = discovered
    if not (window_start <= guard_at < window_start + window_len):
        print("  [FAIL] Synthetic fixture: discovered title window missed the guard")
        return False
    print("  [PASS] Synthetic fixture: title window discovery recovers a pre-tail guard")

    uncontextual = b"if(Ue().isNonInteractiveCLIMode())return null;"
    uncontextual_at = 2_097_152

    def fake_fetch_uncontextual(url: str, range_header: str, retries: int = 3):
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
        if not match:
            raise ValueError(f"unexpected range header: {range_header}")
        start, end = int(match.group(1)), int(match.group(2))
        length = end - start + 1
        blob = bytearray(length)
        payload_end = uncontextual_at + len(uncontextual)
        overlap_start = max(start, uncontextual_at)
        overlap_end = min(end + 1, payload_end)
        if overlap_start < overlap_end:
            src = overlap_start - uncontextual_at
            dst = overlap_start - start
            span = overlap_end - overlap_start
            blob[dst : dst + span] = uncontextual[src : src + span]
        return bytes(blob), f"bytes {start}-{end}/{total_size}", 206

    try:
        globals()["fetch_range"] = fake_fetch_uncontextual
        rejected = discover_title_window("https://example.invalid/droid", total_size, tail_start)
    finally:
        globals()["fetch_range"] = original_fetch_range

    if rejected is not None:
        print("  [FAIL] Synthetic fixture: uncontextual pre-tail guards were accepted")
        return False
    print("  [PASS] Synthetic fixture: title window discovery stays fail-closed without context")

    # 7. Runtime key registry lives before the last-60MB tail. Discovery must
    # recover the unique map without accepting an uncontextual ctrl-p token.
    runtime_map = (
        b'var hX={b:"ctrl-b",c:"ctrl-c",d:"ctrl-d",e:"ctrl-e",f:"ctrl-f",'
        b'g:"ctrl-g",j:"ctrl-j",l:"ctrl-l",n:"ctrl-n",o:"ctrl-o",p:"ctrl-p",'
        b'r:"ctrl-r",t:"ctrl-t",x:"ctrl-x",y:"ctrl-y",z:"ctrl-z"};'
    )
    runtime_at = 3_145_728

    def fake_fetch_runtime(url: str, range_header: str, retries: int = 3):
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
        if not match:
            raise ValueError(f"unexpected range header: {range_header}")
        start, end = int(match.group(1)), int(match.group(2))
        length = end - start + 1
        blob = bytearray(length)
        payload_end = runtime_at + len(runtime_map)
        overlap_start = max(start, runtime_at)
        overlap_end = min(end + 1, payload_end)
        if overlap_start < overlap_end:
            src = overlap_start - runtime_at
            dst = overlap_start - start
            span = overlap_end - overlap_start
            blob[dst : dst + span] = runtime_map[src : src + span]
        return bytes(blob), f"bytes {start}-{end}/{total_size}", 206

    try:
        globals()["fetch_range"] = fake_fetch_runtime
        discovered_runtime = discover_runtime_window(
            "https://example.invalid/droid", total_size, tail_start
        )
    finally:
        globals()["fetch_range"] = original_fetch_range

    if discovered_runtime is None:
        print("  [FAIL] Synthetic fixture: runtime window before tail was not discovered")
        return False
    runtime_start, runtime_len = discovered_runtime
    if not (runtime_at <= runtime_start < runtime_at + len(runtime_map)):
        print("  [FAIL] Synthetic fixture: discovered runtime window missed the registry")
        return False
    if runtime_len != len(RUNTIME_MAP_MARKER):
        print("  [FAIL] Synthetic fixture: discovered runtime window used an unexpected length")
        return False
    print("  [PASS] Synthetic fixture: runtime window discovery recovers a pre-tail registry")

    lone_ctrl_p = b'p:"ctrl-p"'
    lone_at = 4_194_304

    def fake_fetch_lone_ctrl_p(url: str, range_header: str, retries: int = 3):
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
        if not match:
            raise ValueError(f"unexpected range header: {range_header}")
        start, end = int(match.group(1)), int(match.group(2))
        length = end - start + 1
        blob = bytearray(length)
        payload_end = lone_at + len(lone_ctrl_p)
        overlap_start = max(start, lone_at)
        overlap_end = min(end + 1, payload_end)
        if overlap_start < overlap_end:
            src = overlap_start - lone_at
            dst = overlap_start - start
            span = overlap_end - overlap_start
            blob[dst : dst + span] = lone_ctrl_p[src : src + span]
        return bytes(blob), f"bytes {start}-{end}/{total_size}", 206

    try:
        globals()["fetch_range"] = fake_fetch_lone_ctrl_p
        rejected_runtime = discover_runtime_window(
            "https://example.invalid/droid", total_size, tail_start
        )
    finally:
        globals()["fetch_range"] = original_fetch_range

    if rejected_runtime is not None:
        print("  [FAIL] Synthetic fixture: uncontextual ctrl-p token was accepted")
        return False
    print("  [PASS] Synthetic fixture: runtime window discovery stays fail-closed without registry context")

    original_release_windows = dict(RELEASE_WINDOWS)
    manifest_calls: list[tuple[int, int]] = []
    tail_blob = (
        b"function generateTitle(){let firstUserText='hi';"
        b"if(Ue().isNonInteractiveCLIMode())return null;"
        b"return formatTitle(res);}"
    )
    manifest_blobs = {
        10: b"KEYMAP",
        40: b"RUNTIME",
        80: tail_blob,
    }

    def fake_fetch_manifest(url: str, range_header: str, retries: int = 3):
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
        if not match:
            raise ValueError(f"unexpected range header: {range_header}")
        start, end = int(match.group(1)), int(match.group(2))
        manifest_calls.append((start, end))
        blob = manifest_blobs[start]
        if len(blob) != end - start + 1:
            raise ValueError("unexpected manifest window length")
        return blob, f"bytes {start}-{end}/100", 206

    RELEASE_WINDOWS.clear()
    RELEASE_WINDOWS["9.9.9|x64"] = {
        "size": 80 + len(tail_blob),
        "layout": "binary-records",
        "windows": [[10, 6], [40, 7], [80, len(tail_blob)]],
    }
    try:
        globals()["fetch_range"] = fake_fetch_manifest
        try:
            test_variant("9.9.9", "x64")
        except patch_keybindings.PatchError:
            pass
    finally:
        globals()["fetch_range"] = original_fetch_range
        RELEASE_WINDOWS.clear()
        RELEASE_WINDOWS.update(original_release_windows)

    if manifest_calls != [(10, 15), (40, 46), (80, 80 + len(tail_blob) - 1)]:
        print("  [FAIL] Synthetic fixture: 3-window manifest was not fetched as written")
        return False
    print("  [PASS] Synthetic fixture: 3-window manifest is fetched and assembled")

    title_blob = (
        b"function generateTitle(){let firstUserText='hi';"
        b"if(Ue().isNonInteractiveCLIMode())return null;"
        b"return formatTitle(res);}"
    )
    pre_title_calls: list[tuple[int, int]] = []
    pre_title_blobs = {
        10: b"KEYMAP",
        40: title_blob,
        200: b"TAILONLY",
    }

    def fake_fetch_pre_title(url: str, range_header: str, retries: int = 3):
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
        if not match:
            raise ValueError(f"unexpected range header: {range_header}")
        start, end = int(match.group(1)), int(match.group(2))
        pre_title_calls.append((start, end))
        blob = pre_title_blobs[start]
        if len(blob) != end - start + 1:
            raise ValueError("unexpected manifest window length")
        return blob, f"bytes {start}-{end}/100", 206

    RELEASE_WINDOWS.clear()
    RELEASE_WINDOWS["9.9.8|x64"] = {
        "size": 208,
        "layout": "binary-records",
        "windows": [[10, 6], [40, len(title_blob)], [200, 8]],
    }
    try:
        globals()["fetch_range"] = fake_fetch_pre_title
        try:
            ok_pre_title = test_variant("9.9.8", "x64")
        except patch_keybindings.PatchError:
            ok_pre_title = False
        except (KeyError, RuntimeError, ValueError):
            print("  [FAIL] Synthetic fixture: title in a non-tail recorded window was not used")
            return False
    finally:
        globals()["fetch_range"] = original_fetch_range
        RELEASE_WINDOWS.clear()
        RELEASE_WINDOWS.update(original_release_windows)

    if ok_pre_title:
        print("  [FAIL] Synthetic fixture: 3-window pre-tail title unexpectedly fully patched")
        return False
    if pre_title_calls[:3] != [(10, 15), (40, 40 + len(title_blob) - 1), (200, 207)]:
        print("  [FAIL] Synthetic fixture: pre-tail title manifest was not fetched as written")
        return False
    if any(start == 0 for start, _end in pre_title_calls):
        print("  [FAIL] Synthetic fixture: title in a recorded window still triggered discovery")
        return False
    print("  [PASS] Synthetic fixture: recorded non-tail title window is used without rediscovery")

    return True


ARCH_VARIANTS = ["x64", "x64-baseline"]
TILE_SIZE = 8 * 1024 * 1024
TILE_OVERLAP = 16 * 1024


def parse_elf_sections(url: str) -> list[tuple[str, int, int]]:
    """Fetch ELF section table via minimal ranges (~4KB). Returns [(name, offset, size)]."""
    header, _, status = fetch_range(url, "bytes=0-63")
    if status == 200 or header[:5] != b"\x7fELF\x02":
        return []
    e_shoff = struct.unpack_from("<Q", header, 40)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", header, 58)
    if e_shoff == 0 or e_shnum == 0:
        return []
    table_bytes = e_shentsize * e_shnum
    table, _, _ = fetch_range(url, f"bytes={e_shoff}-{e_shoff + table_bytes - 1}")
    raw_sections = []
    for i in range(e_shnum):
        name_off, _type, _flags, _addr, offset, size = struct.unpack_from(
            "<IIQQQQ", table, i * e_shentsize
        )
        raw_sections.append((name_off, offset, size))
    if e_shstrndx >= len(raw_sections):
        return []
    str_off, str_size = raw_sections[e_shstrndx][1], raw_sections[e_shstrndx][2]
    names, _, _ = fetch_range(url, f"bytes={str_off}-{str_off + str_size - 1}")
    sections = []
    for name_off, offset, size in raw_sections:
        end = names.find(b"\x00", name_off)
        name = names[name_off:end].decode("ascii", "replace") if end != -1 else ""
        sections.append((name, offset, size))
    return sections


def _cluster_signature_in(tile: bytes) -> tuple[int, int] | None:
    km_bin = patch_keybindings._find_binary_record_keymap(tile, patched=False)
    if km_bin:
        return km_bin[0], km_bin[2]
    offset = 0
    while True:
        position = tile.find(b"ctrl-g\x00", offset)
        if position == -1:
            break
        match = patch_keybindings.TABLE_RE.match(tile, position)
        if match and patch_keybindings.RANGE_GAP not in match.group(0):
            return position, match.end()
        offset = position + 1
    return None


def discover_keymap_window(url: str, total_size: int, tail_start: int) -> tuple[int, int] | None:
    """Locate the keymap cluster for an unseen release and return (start, length)."""
    try:
        sections = parse_elf_sections(url)
        bun_sections = [(o, s) for n, o, s in sections if n == ".bun" and s > 1_000_000]
        if bun_sections:
            search_start, search_size = bun_sections[0]
        else:
            search_start, search_size = 80_000_000, max(0, total_size - 80_000_000)
    except Exception:
        search_start, search_size = 80_000_000, max(0, total_size - 80_000_000)

    lo = max(0, search_start)
    hi = min(lo + search_size, tail_start)
    pos = lo
    while pos < hi:
        chunk_start = pos
        chunk_end = min(hi, pos + TILE_SIZE + TILE_OVERLAP)
        tile, _, _ = fetch_range(url, f"bytes={chunk_start}-{chunk_end - 1}")
        cluster = _cluster_signature_in(tile)
        if cluster:
            c_start, c_end = cluster
            kstart = chunk_start + c_start
            kend = chunk_start + c_end
            window_start = max(0, kstart - 16384)
            window_len = (kend - kstart) + 32768
            return window_start, window_len
        pos = chunk_end - TILE_OVERLAP
        if pos <= chunk_start:
            break
    return None


def discover_title_window(url: str, total_size: int, tail_start: int) -> tuple[int, int] | None:
    """Locate a unique contextual titling guard before the last-60MB tail."""
    lo = 0
    hi = min(max(0, tail_start), max(0, total_size))
    found: list[tuple[int, int]] = []
    pos = lo
    while pos < hi:
        chunk_start = pos
        chunk_end = min(hi, pos + TILE_SIZE + TILE_OVERLAP)
        tile, _, _ = fetch_range(url, f"bytes={chunk_start}-{chunk_end - 1}")
        for match in find_valid_matches(tile):
            abs_start = chunk_start + match.start()
            abs_end = chunk_start + match.end()
            if not any(start == abs_start for start, _end in found):
                found.append((abs_start, abs_end))
        next_pos = chunk_end - TILE_OVERLAP
        if next_pos <= chunk_start:
            break
        pos = next_pos
    if len(found) != 1:
        return None
    kstart, kend = found[0]
    window_start = max(0, kstart - 16384)
    window_len = (kend - kstart) + 32768
    return window_start, window_len


RUNTIME_MAP_MARKER = b'p:"ctrl-p"'
RUNTIME_MAP_CONTEXT = (b'b:"ctrl-b"', b'c:"ctrl-c"', b'x:"ctrl-x"', b'z:"ctrl-z"')
# Help/display chords sit a few MiB before the map; dispatch sits after it.
# v0.223.0 chords are ~9.36 MiB before the registry, so 8 MiB is not enough.
RUNTIME_WINDOW_BEFORE = 16 * 1024 * 1024
RUNTIME_WINDOW_AFTER = 160 * 1024


def _runtime_map_offsets(tile: bytes) -> list[int]:
    found: list[int] = []
    offset = 0
    while True:
        position = tile.find(RUNTIME_MAP_MARKER, offset)
        if position == -1:
            return found
        window = tile[max(0, position - 300) : min(len(tile), position + 300)]
        if all(marker in window for marker in RUNTIME_MAP_CONTEXT):
            found.append(position)
        offset = position + 1


def discover_runtime_window(url: str, total_size: int, tail_start: int) -> tuple[int, int] | None:
    """Locate a unique runtime key-ID map before the last-60MB tail."""
    lo = 0
    hi = min(max(0, tail_start), max(0, total_size))
    found: list[int] = []
    pos = lo
    while pos < hi:
        chunk_start = pos
        chunk_end = min(hi, pos + TILE_SIZE + TILE_OVERLAP)
        tile, _, _ = fetch_range(url, f"bytes={chunk_start}-{chunk_end - 1}")
        for relative in _runtime_map_offsets(tile):
            abs_start = chunk_start + relative
            if abs_start not in found:
                found.append(abs_start)
        next_pos = chunk_end - TILE_OVERLAP
        if next_pos <= chunk_start:
            break
        pos = next_pos
    if len(found) != 1:
        return None
    kstart = found[0]
    return kstart, len(RUNTIME_MAP_MARKER)


def _count_chord(data: bytes, chord: bytes) -> int:
    """Count non-word-extended chord occurrences (e.g. avoid Ctrl+Invio for Ctrl+I)."""
    cnt = 0
    pos = 0
    chord_len = len(chord)
    while True:
        pos = data.find(chord, pos)
        if pos == -1:
            break
        end = pos + chord_len
        if end >= len(data) or not (65 <= data[end] <= 90 or 97 <= data[end] <= 122):
            cnt += 1
        pos += chord_len
    return cnt


def display_chord_error(
    original: bytes, patched: bytes, already_rotated: bool
) -> str | None:
    """Return a fail-closed diagnostic, or None when present styles rotated.

    Unused human-chord styles (``Ctrl + N``, ``Ctrl-N``) are skipped. A release
    still fails if every scanned style is empty.
    """
    saw_chords = False
    for template in (b"Ctrl+%s", b"Ctrl + %s", b"ctrl+%s", b"Ctrl-%s"):
        before = {
            letter: _count_chord(original, template % letter)
            for letter in (b"G", b"N", b"P", b"I")
        }
        after = {
            letter: _count_chord(patched, template % letter)
            for letter in (b"G", b"N", b"P", b"I")
        }
        if already_rotated:
            if after[b"I"] + after[b"P"] + after[b"G"] == 0:
                continue
            saw_chords = True
            continue
        if before[b"G"] + before[b"N"] + before[b"P"] == 0:
            continue
        saw_chords = True
        expected = {b"G": before[b"P"], b"N": 0, b"P": before[b"N"], b"I": before[b"G"]}
        if after != expected:
            return f"Chord display counts did not rotate ({template!r})"
    if not saw_chords:
        if already_rotated:
            return "Rotated display chords are absent across all scanned bytes"
        return "display chords absent across all scanned bytes"
    return None


def test_variant(ver: str, arch: str, prefer_cached: bool = False) -> bool:
    needs_harvest = False
    cached_path = Path(".tmp/factory-releases") / f"droid-{ver}-{arch}"
    used_cache = prefer_cached and cached_path.is_file() and cached_path.stat().st_size > 50_000_000
    if used_cache:
        data = cached_path.read_bytes()
        tail_start = len(data) - min(60_000_000, len(data))
        total_size = len(data)
        keybinding_data = data
        title_source = data[tail_start:]
        url = ""
        key = f"{ver}|{arch}"
    else:
        url = f"{BASE_URL}/{ver}/linux/{arch}/droid"
        key = f"{ver}|{arch}"
        entry = RELEASE_WINDOWS.get(key)
        if entry:
            windows = entry.get("windows", [])
            if not windows:
                raise ValueError(f"invalid windows manifest entry for {key}")
            pieces: list[tuple[int, bytes]] = []
            for w_start, w_len in windows:
                blob, content_range, response_status = fetch_range(
                    url, f"bytes={w_start}-{w_start + w_len - 1}"
                )
                pieces.append((w_start, blob))
            pieces.sort(key=lambda item: item[0])
            data = pieces[-1][1]
            tail_start = pieces[-1][0]
            total_size = entry.get("size", tail_start + len(data))
            keybinding_data = assemble_range_windows(pieces)
            titled = [blob for _, blob in pieces if find_valid_matches(blob)]
            title_source = titled[0] if len(titled) == 1 else data
        else:
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
            title_source = data
            keybinding_data = data
            if keybinding_expected(ver):
                try:
                    patch_keybindings.apply_patch_bytes(data)
                except patch_keybindings.PatchError:
                    needs_harvest = True
            if len(find_valid_matches(title_source)) != 1:
                needs_harvest = True
            if needs_harvest:
                bun_sections = []
                try:
                    bun_sections = [
                        (offset, size)
                        for name, offset, size in parse_elf_sections(url)
                        if name == ".bun" and size > 1_000_000
                    ]
                except Exception:
                    bun_sections = []
                import cluster_harvest

                cluster_harvest.fetch_range = fetch_range
                cluster_harvest.find_valid_matches = find_valid_matches
                cluster_harvest.assemble_range_windows = assemble_range_windows
                harvested = cluster_harvest.harvest_missing_clusters(
                    url,
                    total_size=total_size,
                    tail_start=tail_start,
                    tail_data=data,
                    bun_sections=bun_sections,
                    keybindings=keybinding_expected(ver),
                )
                if harvested.error:
                    print(f"  [FAIL] Harvest rejected v{ver} ({arch}): {harvested.error}")
                    return False
                pieces = list(harvested.windows) + [(tail_start, data)]
                keybinding_data = assemble_range_windows(pieces)
                title_source = harvested.title_source if harvested.title_source is not None else data
                for w_start, blob in harvested.windows:
                    print(f"  [DISCOVERED] Harvest window for {key}: [{w_start}, {len(blob)}]")

    valid_matches = find_valid_matches(title_source)
    if len(valid_matches) != 1 and used_cache:
        valid_matches = find_valid_matches(data)
        title_source = data
    elif len(valid_matches) != 1 and not needs_harvest:
        discovered_title = discover_title_window(url, total_size, tail_start)
        if discovered_title:
            t_start, t_len = discovered_title
            title_source, _, _ = fetch_range(url, f"bytes={t_start}-{t_start + t_len - 1}")
            valid_matches = find_valid_matches(title_source)
            print(f"  [DISCOVERED] Title window for {key}: [{t_start}, {t_len}]")
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
        patched_keybindings = patch_keybindings.apply_patch_bytes(keybinding_data)
    except Exception as error:
        print(f"  [FAIL] Keybinding patch rejected v{ver} ({arch}): {error}")
        return False

    if len(patched_keybindings) != len(keybinding_data):
        print(f"  [FAIL] Keybinding patch changed binary size for v{ver} ({arch})")
        return False
    already_rotated = patched_keybindings == keybinding_data
    if already_rotated:
        display_state = patch_keybindings.inventory_kinds(keybinding_data).get("display")
        if display_state != "rotated":
            print(f"  [FAIL] Keybinding patch made no change for v{ver} ({arch})")
            return False
    if patch_keybindings.apply_patch_bytes(patched_keybindings) != patched_keybindings:
        print(f"  [FAIL] Keybinding patch is not idempotent for v{ver} ({arch})")
        return False

    # Present human-chord styles must rotate. Unused styles (a release that
    # never prints "Ctrl + N" or "Ctrl-N") are skipped rather than treated as
    # a vacuous absence.
    chord_error = display_chord_error(
        keybinding_data, patched_keybindings, already_rotated
    )
    if chord_error:
        print(f"  [FAIL] {chord_error} for v{ver} ({arch})")
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


def test_version(ver: str, prefer_cached: bool = False) -> bool:
    print(f"Testing release v{ver} (both AVX2 and baseline)...")
    for arch in ARCH_VARIANTS:
        if not test_variant(ver, arch, prefer_cached=prefer_cached):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-version and synthetic test suite for Droid patcher")
    parser.add_argument("--offline", action="store_true", help="Run only offline synthetic fixture tests")
    parser.add_argument("--latest", action="store_true", help="Fetch and include the latest upstream release")
    parser.add_argument("--cached", action="store_true", help="Prefer local cached binaries from .tmp/factory-releases")
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
        if not test_version(v, prefer_cached=args.cached):
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
