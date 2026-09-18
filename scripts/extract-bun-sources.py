#!/usr/bin/env python3
"""Extract searchable Bun bundle data from a Linux ELF executable.

This is a forensic extractor, not a native-code decompiler. It preserves the
raw Bun and read-only-data sections, records printable source-like runs with
their section-relative offsets, and emits marker locations for comparing
release binaries.
"""

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path


UTF8_CHAR_RE = (
    rb"(?:[\x09\x0a\x0d\x20-\x7e]|[\xc2-\xdf][\x80-\xbf]|"
    rb"[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3})"
)


def make_run_pattern(minimum_run: int) -> re.Pattern[bytes]:
    return re.compile(UTF8_CHAR_RE + f"{{{minimum_run},}}".encode("ascii"))

DEFAULT_MARKERS = (
    b"modelCycle",
    b"openTextAndWait",
    b"editorOverflowHint",
    b"sourceMappingURL",
    b"/$bunfs/root/",
)
SOURCE_HINTS = (
    b"function",
    b"=>",
    b"return",
    b"sourceMappingURL",
    b"/$bunfs/root/",
    b"modelCycle",
    b"openTextAndWait",
)
SECTION_HEADER = struct.Struct("<IIQQQQIIQQ")
ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")


class ExtractionError(RuntimeError):
    """Raised when the input is not a supported ELF executable."""


def _read_c_string(table: bytes, start: int) -> str:
    end = table.find(b"\x00", start)
    if end == -1:
        raise ExtractionError("ELF section-name table is malformed")
    return table[start:end].decode("utf-8", "replace")


def parse_elf_sections(data: bytes) -> dict[str, tuple[int, int]]:
    """Return section names mapped to (file offset, byte size)."""
    if len(data) < ELF_HEADER.size or data[:4] != b"\x7fELF":
        raise ExtractionError("input is not an ELF executable")
    ident = data[:16]
    if ident[4] != 2 or ident[5] != 1:
        raise ExtractionError("only 64-bit little-endian ELF is supported")

    header = ELF_HEADER.unpack_from(data)
    section_offset = header[6]
    section_size = header[11]
    section_count = header[12]
    names_index = header[13]
    if section_size != SECTION_HEADER.size:
        raise ExtractionError("unsupported ELF section-header size")
    section_table_end = section_offset + section_size * section_count
    if section_table_end > len(data) or names_index >= section_count:
        raise ExtractionError("ELF section table is out of bounds")

    headers = [
        SECTION_HEADER.unpack_from(data, section_offset + index * section_size)
        for index in range(section_count)
    ]
    names_offset = headers[names_index][4]
    names_size = headers[names_index][5]
    names = data[names_offset : names_offset + names_size]
    if len(names) != names_size:
        raise ExtractionError("ELF section-name table is out of bounds")

    sections = {}
    for name_offset, _, _, _, file_offset, size, _, _, _, _ in headers:
        name = _read_c_string(names, name_offset)
        if file_offset + size > len(data):
            raise ExtractionError(f"ELF section {name!r} is out of bounds")
        sections[name] = (file_offset, size)
    return sections


def find_all(data: bytes, marker: bytes) -> list[int]:
    return [match.start() for match in re.finditer(re.escape(marker), data)]


def source_like(text: bytes) -> bool:
    return sum(hint in text for hint in SOURCE_HINTS) >= 2


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def extract(
    binary: Path,
    output: Path,
    minimum_run: int,
    markers: tuple[bytes, ...],
    write_fragments: bool,
) -> dict:
    data = binary.read_bytes()
    sections = parse_elf_sections(data)
    selected = {name: sections[name] for name in (".bun", ".rodata") if name in sections}
    if ".bun" not in selected:
        raise ExtractionError("ELF executable has no .bun section")

    section_dir = output / "sections"
    section_dir.mkdir(parents=True, exist_ok=True)
    if write_fragments:
        (output / "source-fragments").mkdir(parents=True, exist_ok=True)

    manifest = {
        "input": str(binary.resolve()),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "sections": {
            name: {"offset": offset, "size": size}
            for name, (offset, size) in sections.items()
            if name in selected
        },
        "minimum_printable_run": minimum_run,
        "write_fragments": write_fragments,
        "markers": {},
        "runs": {},
        "source_fragments": [],
    }

    searchable = output / "searchable.txt"
    strings_path = output / "strings.jsonl"
    with (
        searchable.open("w", encoding="utf-8") as searchable_file,
        strings_path.open("w", encoding="utf-8") as strings_file,
    ):
        for name, (offset, size) in selected.items():
            section_data = data[offset : offset + size]
            section_file = section_dir / f"{name.lstrip('.') or 'unnamed'}.bin"
            section_file.write_bytes(section_data)
            run_pattern = make_run_pattern(minimum_run)
            kept_runs = 0
            for run in run_pattern.finditer(section_data):
                text = run.group()
                kept_runs += 1
                record = {
                    "section": name,
                    "offset": run.start(),
                    "length": len(text),
                    "text": text.decode("utf-8", "replace"),
                }
                strings_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                searchable_file.write(
                    f"\n/* section={name} offset={run.start()} length={len(text)} */\n"
                )
                searchable_file.write(record["text"])
                searchable_file.write("\n")
                if write_fragments and len(text) >= 256 and source_like(text):
                    fragment = (
                        output
                        / "source-fragments"
                        / f"{name.lstrip('.')}-{run.start():012x}.js"
                    )
                    fragment.write_bytes(text)
                    manifest["source_fragments"].append(
                        {
                            "path": str(fragment.relative_to(output)),
                            "section": name,
                            "offset": run.start(),
                            "length": len(text),
                        }
                    )
            manifest["runs"][name] = {
                "total": kept_runs,
                "kept": kept_runs,
            }
            for marker in markers:
                manifest["markers"].setdefault(marker.decode("ascii"), {})[name] = find_all(
                    section_data, marker
                )

    write_json(output / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-run", type=int, default=64)
    parser.add_argument(
        "--write-fragments",
        action="store_true",
        help="also write source-like runs as individual .js fragment files",
    )
    args = parser.parse_args()
    if args.min_run < 1:
        parser.error("--min-run must be positive")
    try:
        manifest = extract(
            args.binary,
            args.out,
            args.min_run,
            DEFAULT_MARKERS,
            args.write_fragments,
        )
    except (OSError, ExtractionError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"Extracted {manifest['runs'].get('.bun', {}).get('kept', 0)} "
        f"printable .bun runs to '{args.out}'."
    )
    print(f"Manifest: '{args.out / 'manifest.json'}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
