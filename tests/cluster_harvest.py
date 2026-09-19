"""Missing-cluster harvest for unseen Factory CLI releases.

Discover required patcher clusters that left the last-60MB tail, fetch small
windows, and assemble them without downloading the full binary twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import patch_keybindings

DISPLAY_ABSENT = "display chords absent across all scanned bytes"
TILE = 8 * 1024 * 1024
OVERLAP = 16 * 1024
WINDOW_PAD = 16 * 1024
MERGE_GAP = 64 * 1024
STRADDLE = 16 * 1024
FALLBACK_BUN_START = 80_000_000

fetch_range = None
find_valid_matches = None
assemble_range_windows = None


@dataclass
class HarvestResult:
    windows: list[tuple[int, bytes]] = field(default_factory=list)
    title_source: bytes | None = None
    error: str | None = None


def _fetch(url: str, range_header: str):
    if fetch_range is None:
        raise RuntimeError("harvest fetch_range is not bound")
    return fetch_range(url, range_header)


def _normalize(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    ordered = sorted((start, end) for start, end in intervals if end > start)
    if not ordered:
        return []
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _subtract(
    universe: list[tuple[int, int]], scanned: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    scanned_norm = _normalize(scanned)
    for u_start, u_end in _normalize(universe):
        cursor = u_start
        for s_start, s_end in scanned_norm:
            if s_end <= cursor or s_start >= u_end:
                continue
            if cursor < s_start:
                result.append((cursor, min(s_start, u_end)))
            cursor = max(cursor, s_end)
            if cursor >= u_end:
                break
        if cursor < u_end:
            result.append((cursor, u_end))
    return [(start, end) for start, end in result if end > start]


def _slice_store(store: list[tuple[int, bytes]], start: int, end: int) -> bytes:
    pieces = []
    cursor = start
    for piece_start, blob in sorted(store, key=lambda item: item[0]):
        piece_end = piece_start + len(blob)
        if piece_end <= cursor or piece_start >= end:
            continue
        if piece_start > cursor:
            return b""
        take_start = cursor - piece_start
        take_end = min(len(blob), end - piece_start)
        pieces.append(blob[take_start:take_end])
        cursor += take_end - take_start
        if cursor >= end:
            break
    if cursor != end:
        return b""
    return b"".join(pieces)


def _ensure_range(
    url: str, start: int, end: int, total_size: int, store: list[tuple[int, bytes]]
) -> bytes:
    start = max(0, start)
    end = min(total_size, end)
    if end <= start:
        return b""
    covered = [(piece_start, piece_start + len(blob)) for piece_start, blob in store]
    for hole_start, hole_end in _subtract([(start, end)], covered):
        blob, _, _ = _fetch(url, f"bytes={hole_start}-{hole_end - 1}")
        store.append((hole_start, blob))
    return _slice_store(store, start, end)


def _cluster_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    ordered = sorted(spans)
    clustered = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = clustered[-1]
        if start <= last_end + MERGE_GAP:
            clustered[-1] = (last_start, max(last_end, end))
        else:
            clustered.append((start, end))
    return clustered


def _pad_window(start: int, end: int, total_size: int) -> tuple[int, int]:
    return max(0, start - WINDOW_PAD), min(total_size, end + WINDOW_PAD)


def _merge_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not windows:
        return []
    ordered = sorted(windows)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + MERGE_GAP:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _title_hits(data: bytes) -> list[tuple[int, int, str]] | str:
    matches = find_valid_matches(data)
    if len(matches) > 1:
        return "ambiguous"
    if not matches:
        return []
    match = matches[0]
    return [(match.start(), match.end(), "unpatched")]


def _kind_hits(blob: str | bytes, kind: str) -> list[tuple[int, int, str]] | str:
    if kind == "title":
        return _title_hits(blob)
    located = patch_keybindings.locate_kinds(blob)[kind]
    return located


def _absolute_kind_hits(
    pieces: list[tuple[int, bytes]], kind: str
) -> list[tuple[int, int, str]] | str:
    found: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int, str]] = set()
    for start, blob in pieces:
        hits = _kind_hits(blob, kind)
        if hits == "ambiguous":
            return "ambiguous"
        for rel_start, rel_end, state in hits:
            item = (start + rel_start, start + rel_end, state)
            if item not in seen:
                seen.add(item)
                found.append(item)
    if kind == "keymap":
        if not pieces:
            return []
        assembled = assemble_range_windows(pieces)
        located = patch_keybindings.locate_keymap(assembled)
        if located == "ambiguous":
            return "ambiguous"
        if not located:
            return []
        if len(located) != 1:
            return "ambiguous"
        _rel_start, _rel_end, state = located[0]
        return [(pieces[0][0], pieces[0][0] + 1, state)]
    if kind != "display" and len({item[0] for item in found}) > 1:
        return "ambiguous"
    return found


def _inventory_pieces(pieces: list[tuple[int, bytes]], keybindings: bool) -> dict[str, str | None]:
    inventory: dict[str, str | None] = {}
    kinds = ["title"]
    if keybindings:
        kinds.extend(patch_keybindings.KEYBINDING_HARVEST_KINDS)
    for kind in kinds:
        hits = _absolute_kind_hits(pieces, kind)
        if hits == "ambiguous":
            inventory[kind] = "ambiguous"
            continue
        if kind == "display":
            states = {state for _start, _end, state in hits}
            if not hits:
                inventory[kind] = None
            elif "unpatched" in states and "rotated" in states:
                inventory[kind] = "ambiguous"
            elif "unpatched" in states:
                inventory[kind] = "unpatched"
            elif "rotated" in states:
                inventory[kind] = "rotated"
            else:
                inventory[kind] = "unresolved"
            continue
        if not hits:
            inventory[kind] = None
        elif len(hits) != 1:
            inventory[kind] = "ambiguous"
        else:
            inventory[kind] = hits[0][2]
    return inventory


def _missing_kinds(inventory: dict[str, str | None], keybindings: bool) -> list[str]:
    required = ["title"]
    if keybindings:
        required.extend(patch_keybindings.KEYBINDING_HARVEST_KINDS)
    missing = []
    for kind in required:
        state = inventory.get(kind)
        if state == "ambiguous":
            return [f"ambiguous:{kind}"]
        if state is None:
            missing.append(kind)
    return missing


def _scan_tile_hits(blob: bytes, kinds: list[str]) -> dict[str, list[tuple[int, int, str]]]:
    found: dict[str, list[tuple[int, int, str]]] = {kind: [] for kind in kinds}
    for kind in kinds:
        if kind == "keymap":
            for start, end in patch_keybindings.raw_keymap_spans(blob):
                found[kind].append((start, end, "raw"))
            continue
        hits = _kind_hits(blob, kind)
        if hits == "ambiguous":
            continue
        found[kind].extend(hits)
    return found


def _add_hit_windows(
    url: str,
    total_size: int,
    store: list[tuple[int, bytes]],
    windows: dict[tuple[int, int], None],
    tile_start: int,
    hits: dict[str, list[tuple[int, int, str]]],
    tail_start: int,
    tail_data: bytes,
) -> None:
    spans: list[tuple[int, int]] = []
    keymap_spans: list[tuple[int, int]] = []
    for kind, kind_hits in hits.items():
        relative = [(start, end) for start, end, _state in kind_hits]
        if kind == "display":
            relative = _cluster_spans(relative)
        for start, end in relative:
            abs_start = tile_start + start
            abs_end = tile_start + end
            padded = _pad_window(abs_start, abs_end, total_size)
            if kind == "keymap":
                keymap_spans.append(padded)
            else:
                spans.append(padded)
    for start, end in _merge_windows(spans):
        _ensure_range(url, start, end, total_size, store)
        windows[(start, end)] = None
    for start, end in _merge_windows(keymap_spans):
        _ensure_range(url, start, end, total_size, store)
        trial = dict(windows)
        trial[(start, end)] = None
        pieces = [(w_start, _slice_store(store, w_start, w_end)) for w_start, w_end in trial]
        pieces.append((tail_start, tail_data))
        pieces = [(w_start, blob) for w_start, blob in pieces if blob]
        located = patch_keybindings.locate_keymap(assemble_range_windows(pieces))
        if located and located != "ambiguous":
            windows[(start, end)] = None


def _walk_intervals(
    url: str,
    total_size: int,
    intervals: list[tuple[int, int]],
    kinds: list[str],
    store: list[tuple[int, bytes]],
    windows: dict[tuple[int, int], None],
    reverse: bool,
    stop_when=None,
    tail_start: int = 0,
    tail_data: bytes = b"",
) -> int | None:
    stop_at = None
    ordered = sorted(intervals, reverse=reverse)
    for lo, hi in ordered:
        if reverse:
            end = hi
            while end > lo:
                start = max(lo, end - TILE)
                blob = _ensure_range(url, start, min(hi, end + OVERLAP), total_size, store)
                rel_hits = _scan_tile_hits(blob, kinds)
                if any(rel_hits[kind] for kind in kinds):
                    _add_hit_windows(
                        url, total_size, store, windows, start, rel_hits, tail_start, tail_data
                    )
                    if stop_when and stop_when():
                        return start
                if start == lo:
                    break
                end = start + OVERLAP
                if end >= hi:
                    break
        else:
            pos = lo
            while pos < hi:
                chunk_end = min(hi, pos + TILE)
                blob = _ensure_range(
                    url, pos, min(hi, chunk_end + OVERLAP), total_size, store
                )
                rel_hits = _scan_tile_hits(blob, kinds)
                if any(rel_hits[kind] for kind in kinds):
                    _add_hit_windows(
                        url, total_size, store, windows, pos, rel_hits, tail_start, tail_data
                    )
                    if stop_when and stop_when():
                        return pos
                if chunk_end == hi:
                    break
                pos = chunk_end - OVERLAP
                if pos <= lo:
                    break
    return stop_at


def contiguous_title_source(windows: list[tuple[int, bytes]]) -> bytes | None:
    found: dict[tuple[int, int], bytes] = {}
    for start, blob in windows:
        if patch_keybindings.RANGE_GAP in blob:
            continue
        matches = find_valid_matches(blob)
        if len(matches) > 1:
            return None
        if len(matches) != 1:
            continue
        match = matches[0]
        key = (start + match.start(), start + match.end())
        previous = found.get(key)
        if previous is None or len(blob) < len(previous):
            found[key] = blob
    if len(found) != 1:
        return None
    return next(iter(found.values()))


def harvest_missing_clusters(
    url: str,
    total_size: int,
    tail_start: int,
    tail_data: bytes,
    bun_sections: list[tuple[int, int]] | None = None,
    keybindings: bool = True,
) -> HarvestResult:
    store: list[tuple[int, bytes]] = [(tail_start, tail_data)]
    windows: dict[tuple[int, int], None] = {}
    if bun_sections:
        bun = [(start, start + size) for start, size in bun_sections]
    else:
        bun = [(FALLBACK_BUN_START, tail_start)]
    bun = [(start, min(end, tail_start + STRADDLE)) for start, end in bun if end > start]

    def window_pieces() -> list[tuple[int, bytes]]:
        persisted = []
        for start, end in sorted(windows):
            blob = _slice_store(store, start, end)
            if blob:
                persisted.append((start, blob))
        return persisted + [(tail_start, tail_data)]

    inventory = _inventory_pieces(window_pieces(), keybindings)
    missing = _missing_kinds(inventory, keybindings)
    if missing and missing[0].startswith("ambiguous:"):
        return HarvestResult(error=missing[0])
    if not missing:
        title = contiguous_title_source([(tail_start, tail_data)])
        return HarvestResult(windows=[], title_source=title)

    def non_keymap_satisfied() -> bool:
        current = _inventory_pieces(window_pieces(), keybindings)
        needed = [kind for kind in missing if kind != "keymap"]
        return all(current.get(kind) not in (None, "ambiguous") for kind in needed)

    def keymap_validated() -> bool:
        current = _inventory_pieces(window_pieces(), keybindings)
        return current.get("keymap") in ("unpatched", "rotated")

    walk_bound = [(start, min(end, tail_start + STRADDLE)) for start, end in bun]
    if missing == ["keymap"]:
        _walk_intervals(
            url,
            total_size,
            walk_bound,
            ["keymap"],
            store,
            windows,
            reverse=False,
            stop_when=keymap_validated,
            tail_start=tail_start,
            tail_data=tail_data,
        )
    else:
        scan_kinds = list(missing)
        if "keymap" not in scan_kinds and keybindings:
            scan_kinds.append("keymap")
        _walk_intervals(
            url,
            total_size,
            walk_bound,
            scan_kinds,
            store,
            windows,
            reverse=True,
            stop_when=non_keymap_satisfied,
            tail_start=tail_start,
            tail_data=tail_data,
        )
        inventory = _inventory_pieces(window_pieces(), keybindings)
        if inventory.get("keymap") not in ("unpatched", "rotated") and keybindings:
            scanned = [(start, start + len(blob)) for start, blob in store]
            remaining = _subtract(walk_bound, scanned)
            _walk_intervals(
                url,
                total_size,
                remaining,
                ["keymap"],
                store,
                windows,
                reverse=False,
                stop_when=keymap_validated,
                tail_start=tail_start,
                tail_data=tail_data,
            )

    inventory = _inventory_pieces(window_pieces(), keybindings)
    missing = _missing_kinds(inventory, keybindings)
    if missing and missing[0].startswith("ambiguous:"):
        return HarvestResult(error=missing[0])

    if "title" in missing:
        pre_bun = [(0, min(start, tail_start + STRADDLE)) for start, _end in bun]
        scanned = [(start, start + len(blob)) for start, blob in store]
        pre_bun = _subtract(pre_bun, scanned)
        _walk_intervals(
            url,
            total_size,
            pre_bun,
            ["title"],
            store,
            windows,
            reverse=False,
            tail_start=tail_start,
            tail_data=tail_data,
        )
        inventory = _inventory_pieces(window_pieces(), keybindings)
        missing = _missing_kinds(inventory, keybindings)

    if missing:
        scanned = [(start, start + len(blob)) for start, blob in store]
        remaining = _subtract([(0, tail_start + STRADDLE)], scanned)
        _walk_intervals(
            url,
            total_size,
            remaining,
            missing,
            store,
            windows,
            reverse=False,
            tail_start=tail_start,
            tail_data=tail_data,
        )
        inventory = _inventory_pieces(window_pieces(), keybindings)
        missing = _missing_kinds(inventory, keybindings)

    if inventory.get("display") is None and keybindings:
        return HarvestResult(error=DISPLAY_ABSENT)
    if missing and missing[0].startswith("ambiguous:"):
        return HarvestResult(error=missing[0])
    if any(kind != "display" and inventory.get(kind) is None for kind in (
        ["title"] + (list(patch_keybindings.KEYBINDING_HARVEST_KINDS) if keybindings else [])
    )):
        still = [
            kind
            for kind in ["title"]
            + (list(patch_keybindings.KEYBINDING_HARVEST_KINDS) if keybindings else [])
            if inventory.get(kind) is None and kind != "display"
        ]
        return HarvestResult(error=f"missing {', '.join(still)}")

    persisted: list[tuple[int, bytes]] = []
    for start, end in sorted(windows):
        blob = _slice_store(store, start, end)
        if blob:
            persisted.append((start, blob))
    title_source = contiguous_title_source(persisted + [(tail_start, tail_data)])
    return HarvestResult(windows=persisted, title_source=title_source)
