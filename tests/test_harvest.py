#!/usr/bin/env python3
"""Offline fixtures for missing-cluster harvest.

These tests fail closed on address moves the last-60MB tail does not cover.
They use the patcher's decision functions, not raw string finds.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "patches"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import patch_keybindings  # noqa: E402
import test_keybindings  # noqa: E402
import test_versions  # noqa: E402
import cluster_harvest  # noqa: E402

cluster_harvest.fetch_range = test_versions.fetch_range
cluster_harvest.find_valid_matches = test_versions.find_valid_matches
cluster_harvest.assemble_range_windows = test_versions.assemble_range_windows

TITLE_GUARD = (
    b"function generateTitle(){let firstUserText='hi';"
    b"if(Ue().isNonInteractiveCLIMode())return null;"
    b"return formatTitle(res);}"
)


def _range_fetch(blobs: dict[int, bytes], total_size: int):
    def fake_fetch(url: str, range_header: str, retries: int = 3):
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
        if not match:
            raise ValueError(f"unexpected range header: {range_header}")
        start, end = int(match.group(1)), int(match.group(2))
        length = end - start + 1
        blob = bytearray(length)
        for offset, payload in blobs.items():
            payload_end = offset + len(payload)
            overlap_start = max(start, offset)
            overlap_end = min(end + 1, payload_end)
            if overlap_start < overlap_end:
                src = overlap_start - offset
                dst = overlap_start - start
                span = overlap_end - overlap_start
                blob[dst : dst + span] = payload[src : src + span]
        return bytes(blob), f"bytes {start}-{end}/{total_size}", 206

    return fake_fetch


def test_inventory_uses_patcher_predicates() -> None:
    data = test_keybindings.binary_record_fixture()
    kinds = patch_keybindings.inventory_kinds(data)
    assert kinds["keymap"] == "unpatched"
    assert kinds["runtime_registry"] == "unpatched"
    assert kinds["dispatch"] == "unpatched"
    assert kinds["model_cycle"] == "unpatched"
    assert kinds["display"] == "unpatched"
    patched = patch_keybindings.apply_patch_bytes(data)
    rotated = patch_keybindings.inventory_kinds(patched)
    assert rotated["keymap"] == "rotated"
    assert rotated["runtime_registry"] == "rotated"
    assert rotated["display"] == "rotated"


def test_harvest_four_clusters_uses_small_windows() -> None:
    keymap = test_keybindings.keymap_table()
    dispatch = test_keybindings.dispatch_block()
    model = test_keybindings.model_cycle_descriptor()
    runtime = test_keybindings.runtime_key_registry()
    display = test_keybindings.display_block()
    tail_start = 20_000_000
    total_size = tail_start + 1000
    blobs = {
        100_000: keymap,
        200_000: dispatch + model,
        300_000: runtime,
        18_000_000: display,
        19_000_000: TITLE_GUARD,
    }
    fetch_log: list[tuple[int, int]] = []
    original = test_versions.fetch_range

    def logged_fetch(url: str, range_header: str, retries: int = 3):
        data, content_range, status = _range_fetch(blobs, total_size)(
            url, range_header, retries
        )
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
        fetch_log.append((int(match.group(1)), int(match.group(2))))
        return data, content_range, status

    try:
        test_versions.fetch_range = logged_fetch
        cluster_harvest.fetch_range = logged_fetch
        result = cluster_harvest.harvest_missing_clusters(
            "https://example.invalid/droid",
            total_size=total_size,
            tail_start=tail_start,
            tail_data=b"\x00" * 1000,
            bun_sections=[(0, tail_start)],
            keybindings=True,
        )
    finally:
        test_versions.fetch_range = original
        cluster_harvest.fetch_range = original

    if result.error:
        raise AssertionError(result.error)
    windows = [(start, len(blob)) for start, blob in result.windows if start < tail_start]
    if not windows:
        raise AssertionError("harvest returned no pre-tail windows")
    if any(length > 2 * 1024 * 1024 for _start, length in windows):
        raise AssertionError(f"harvest persisted a large pad window: {windows}")
    ordered = sorted(fetch_log)
    for previous, current in zip(ordered, ordered[1:]):
        if previous[1] >= current[0]:
            raise AssertionError(f"harvest fetched overlapping bytes: {previous} {current}")
    assembled = test_versions.assemble_range_windows(
        result.windows + [(tail_start, b"\x00" * 1000)]
    )
    patched = patch_keybindings.apply_patch_bytes(assembled)
    if patched == assembled:
        raise AssertionError("harvested clusters were not rotated")
    if patch_keybindings.apply_patch_bytes(patched) != patched:
        raise AssertionError("harvested rotation is not idempotent")
    if test_versions.find_valid_matches(result.title_source or b"") == []:
        raise AssertionError("harvest missed the pre-tail title guard")


def test_distant_display_hits_persist_small_windows() -> None:
    rest = (
        test_keybindings.keymap_table()
        + test_keybindings.dispatch_block()
        + test_keybindings.model_cycle_descriptor()
        + test_keybindings.runtime_key_registry()
        + TITLE_GUARD
    )
    first = b'onboarding:"Press Ctrl+N to cycle AI models"'
    second = (
        b'editorOverflowHint:"Ctrl+P to open in editor"'
        b'queuedReviewHint:"Ctrl+G to pull top"'
        b'statusBar:"ctrl+N to cycle models"'
    )
    tail_start = 5_000_000
    total_size = tail_start + len(rest)
    blobs = {
        100_000: first,
        4_000_000: second,
        tail_start: rest,
    }
    original = test_versions.fetch_range
    fake = _range_fetch(blobs, total_size)
    try:
        test_versions.fetch_range = fake
        cluster_harvest.fetch_range = fake
        result = cluster_harvest.harvest_missing_clusters(
            "https://example.invalid/droid",
            total_size=total_size,
            tail_start=tail_start,
            tail_data=rest,
            bun_sections=[(0, tail_start)],
            keybindings=True,
        )
    finally:
        test_versions.fetch_range = original
        cluster_harvest.fetch_range = original
    if result.error:
        raise AssertionError(result.error)
    display_windows = [
        (start, len(blob))
        for start, blob in result.windows
        if start < tail_start and (b"Ctrl+" in blob or b"ctrl+" in blob)
    ]
    if not display_windows:
        raise AssertionError("harvest missed the distant display hits")
    if any(length > 256 * 1024 for _start, length in display_windows):
        raise AssertionError(f"display harvest persisted a min-max envelope: {display_windows}")
    if len(display_windows) < 2:
        raise AssertionError(f"distant display hits were collapsed: {display_windows}")


def test_vacuous_display_fails_closed() -> None:
    keymap = test_keybindings.keymap_table()
    dispatch = test_keybindings.dispatch_block()
    model = test_keybindings.model_cycle_descriptor()
    runtime = test_keybindings.runtime_key_registry()
    tail_start = 1_000_000
    total_size = tail_start + 100
    blobs = {
        1000: keymap + dispatch + model + runtime + TITLE_GUARD,
    }
    original = test_versions.fetch_range
    fake = _range_fetch(blobs, total_size)
    try:
        test_versions.fetch_range = fake
        cluster_harvest.fetch_range = fake
        result = cluster_harvest.harvest_missing_clusters(
            "https://example.invalid/droid",
            total_size=total_size,
            tail_start=tail_start,
            tail_data=b"\x00" * 100,
            bun_sections=[(0, tail_start)],
            keybindings=True,
        )
    finally:
        test_versions.fetch_range = original
        cluster_harvest.fetch_range = original
    if result.error != cluster_harvest.DISPLAY_ABSENT:
        raise AssertionError(f"expected display-absent fail, got {result.error!r}")


def test_keymap_only_path_skips_raw_decoy() -> None:
    decoy = (
        b"ctrl-g\x00DECOY00\x00"
        b"ctrl-p\x00DECOY01\x00"
        b"ctrl-slash\x00X\x00"
        b"model-cycle\x00S\x00"
        b"autonomy-cycle\x00J\x00"
    )
    rest = (
        test_keybindings.binary_record_dispatch_block()
        + test_keybindings.binary_record_model_cycle_descriptor()
        + test_keybindings.runtime_key_registry()
        + test_keybindings.display_block()
        + TITLE_GUARD
    )
    real_keymap = test_keybindings.keymap_table_binary_records()
    tail_start = 2_000_000
    total_size = tail_start + len(rest)
    blobs = {100_000: decoy, 800_000: real_keymap, tail_start: rest}
    original = test_versions.fetch_range
    fake = _range_fetch(blobs, total_size)
    try:
        test_versions.fetch_range = fake
        cluster_harvest.fetch_range = fake
        result = cluster_harvest.harvest_missing_clusters(
            "https://example.invalid/droid",
            total_size=total_size,
            tail_start=tail_start,
            tail_data=rest,
            bun_sections=[(0, tail_start)],
            keybindings=True,
        )
    finally:
        test_versions.fetch_range = original
        cluster_harvest.fetch_range = original
    if result.error:
        raise AssertionError(result.error)
    starts = [start for start, _blob in result.windows]
    if any(abs(start - 100_000) < len(decoy) for start in starts):
        raise AssertionError("keymap-only path harvested the raw TABLE_RE decoy")
    if not any(abs(start - 800_000) < 65_536 for start in starts):
        raise AssertionError("keymap-only path missed the validated keymap")


def test_runtime_registry_is_relational() -> None:
    map_only = (
        b'var hX={b:"ctrl-b",c:"ctrl-c",d:"ctrl-d",e:"ctrl-e",f:"ctrl-f",'
        b'g:"ctrl-g",j:"ctrl-j",l:"ctrl-l",n:"ctrl-n",o:"ctrl-o",p:"ctrl-p",'
        b'r:"ctrl-r",t:"ctrl-t",x:"ctrl-x",y:"ctrl-y",z:"ctrl-z"};'
    )
    desc_only = b'ctrlP:bi("p")'
    pair = test_keybindings.runtime_key_registry()
    data = map_only + (b"\x00" * 20_000) + desc_only + (b"\x00" * 20_000) + pair
    kinds = patch_keybindings.inventory_kinds(data)
    if kinds["runtime_registry"] != "unpatched":
        raise AssertionError("unrelated map/desc pair was treated as the registry")
    hits = patch_keybindings.locate_kinds(data)["runtime_registry"]
    if len(hits) != 1:
        raise AssertionError(f"expected one relational registry hit, got {hits}")
    start, end, _state = hits[0]
    pair_at = data.find(pair)
    if not (start < pair_at + len(pair) and end > pair_at):
        raise AssertionError("relational registry hit missed the nearby pair")


def _sparse_display_fixture() -> bytes:
    """0.223.0-shaped help text: Ctrl+ / ctrl+ present, spaced and dashed styles absent."""
    return (
        test_keybindings.keymap_table()
        + test_keybindings.dispatch_block()
        + test_keybindings.model_cycle_descriptor()
        + test_keybindings.runtime_key_registry()
        + b'editorOverflowHint:"Ctrl+P to open in editor"'
        + b'queuedReviewHint:"Ctrl+G to pull top"'
        + b'statusBar:"ctrl+N to cycle models"'
    )


def test_unused_chord_styles_are_not_vacuous_failures() -> None:
    original = _sparse_display_fixture()
    patched = patch_keybindings.apply_patch_bytes(original)
    error = test_versions.display_chord_error(original, patched, already_rotated=False)
    if error:
        raise AssertionError(error)
    absent = test_versions.display_chord_error(
        b"no human chords here", b"no human chords here", already_rotated=False
    )
    if absent != "display chords absent across all scanned bytes":
        raise AssertionError(f"expected all-styles-absent fail, got {absent!r}")


def test_display_outside_bun_is_still_harvested() -> None:
    rest = (
        test_keybindings.keymap_table()
        + test_keybindings.dispatch_block()
        + test_keybindings.model_cycle_descriptor()
        + test_keybindings.runtime_key_registry()
        + TITLE_GUARD
    )
    display = test_keybindings.display_block()
    bun_start = 1_000_000
    tail_start = 2_000_000
    total_size = tail_start + 100
    blobs = {
        50_000: display,
        bun_start + 100_000: rest,
    }
    original = test_versions.fetch_range
    fake = _range_fetch(blobs, total_size)
    try:
        test_versions.fetch_range = fake
        cluster_harvest.fetch_range = fake
        result = cluster_harvest.harvest_missing_clusters(
            "https://example.invalid/droid",
            total_size=total_size,
            tail_start=tail_start,
            tail_data=b"\x00" * 100,
            bun_sections=[(bun_start, 500_000)],
            keybindings=True,
        )
    finally:
        test_versions.fetch_range = original
        cluster_harvest.fetch_range = original
    if result.error:
        raise AssertionError(result.error)
    if not any(b"Ctrl+P" in blob or b"ctrl+N" in blob for _start, blob in result.windows):
        raise AssertionError("display chords outside .bun were not harvested")


def test_title_is_not_matched_across_range_gap() -> None:
    left = b"if(Ue().isNonInteractiveCLIMode())return null;"
    right = b"function generateTitle(){let firstUserText='hi';return formatTitle(res);}"
    if cluster_harvest.contiguous_title_source([(0, left), (1000, right)]) is not None:
        raise AssertionError("split title halves were joined into a title source")
    if cluster_harvest.contiguous_title_source([(40, TITLE_GUARD)]) != TITLE_GUARD:
        raise AssertionError("contiguous title window was not used as title source")
    overlap = TITLE_GUARD + b"xxxx"
    source = cluster_harvest.contiguous_title_source([(0, overlap), (0, TITLE_GUARD)])
    if source not in (overlap, TITLE_GUARD):
        raise AssertionError("overlapping title windows lost the unique title source")


def main() -> int:
    tests = (
        test_inventory_uses_patcher_predicates,
        test_harvest_four_clusters_uses_small_windows,
        test_distant_display_hits_persist_small_windows,
        test_vacuous_display_fails_closed,
        test_keymap_only_path_skips_raw_decoy,
        test_runtime_registry_is_relational,
        test_unused_chord_styles_are_not_vacuous_failures,
        test_display_outside_bun_is_still_harvested,
        test_title_is_not_matched_across_range_gap,
    )
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  [PASS] {test.__name__}")
        except Exception as error:
            failed += 1
            print(f"  [FAIL] {test.__name__}: {error}")
    if failed:
        print("HARVEST FIXTURE TESTS FAILED.")
        return 1
    print("ALL HARVEST FIXTURE TESTS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
