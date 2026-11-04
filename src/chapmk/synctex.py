"""SyncTeX files (PLAN §6.12, S10): read, write with recomputed offsets, map paths, merge."""

from __future__ import annotations

import gzip
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from chapmk.errors import FallbackError

ENCODING = ("utf-8", "surrogateescape")


def read_lines(path: Path) -> list[str]:
    """Lines (without newline) of a ``.synctex.gz`` file."""
    with gzip.open(path, "rb") as f:
        text = f.read().decode(*ENCODING)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def serialise(lines: Sequence[str]) -> bytes:
    """File content for ``lines``. Every ``!<n>`` record is recomputed: ``n`` is the number of
    bytes from the previous ``!`` line (or the file start) to this line (S10)."""
    out = bytearray()
    last = 0
    for line in lines:
        if line.startswith("!"):
            pos = len(out)
            line = f"!{pos - last}"
            last = pos
        out += line.encode(*ENCODING) + b"\n"
    return bytes(out)


def write_lines(path: Path, lines: Sequence[str]) -> None:
    """Write ``lines`` gzip-compressed (deterministic: no file name or time in the header)."""
    _write_gzip(path, serialise(lines))


def _write_gzip(path: Path, data: bytes) -> None:
    with (
        path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=1) as f,
    ):
        f.write(data)


def map_input_paths(lines: Sequence[str], mapping: Sequence[tuple[str, str]]) -> list[str]:
    """Apply prefix substitutions to ``Input:<tag>:<path>`` records. The ``/./`` in
    ``<cwd>/./<relative>`` is kept: ``synctex view`` needs it (S10)."""
    out: list[str] = []
    for line in lines:
        if line.startswith("Input:"):
            _, tag, path = line.split(":", 2)
            for old, new in mapping:
                if path == old or path.startswith(old + "/"):
                    path = new + path[len(old) :]
                    break
            line = f"Input:{tag}:{path}"
        out.append(line)
    return out


def rewrite_paths(src: Path, dst: Path, mapping: Sequence[tuple[str, str]]) -> None:
    """Copy a SyncTeX file with mapped input paths."""
    write_lines(dst, map_input_paths(read_lines(src), mapping))


# --- merge (§6.12, S10) ------------------------------------------------------------------------

HEADER_KEYS = ("Output", "Magnification", "Unit", "X Offset", "Y Offset")


class SyncTexError(FallbackError):
    """SyncTeX files cannot be merged (inconsistent headers, missing sheets)."""


@dataclass
class ParsedSyncTex:
    """Input tags, header values and sheets (records without ``!`` lines) of one file."""

    inputs: dict[str, str]
    header: dict[str, str]
    sheets: dict[int, list[str]]


# Whole-text patterns, each starting with the newline before its line (the text gets one in
# front): a literal first character lets the regex engine skip ahead, ``^`` with MULTILINE
# tries every position (about five times slower on these files).
_INPUT_LINE = re.compile(r"\nInput:([^:\n]*):([^\n]*)")
_HEADER_LINE = re.compile(r"\n(" + "|".join(re.escape(k) for k in HEADER_KEYS) + r"):([^\n]*)")
_MARKER = re.compile(r"\n([{}])(\d+)(?![^\n])")
#: lines a sheet does not keep: offsets (``!``), inputs (recorded separately), empty lines
_SKIPPED = re.compile(r"\n(?:(?:!|Input:)[^\n]*|(?![^\n]))")
#: record type and input tag of a record line (split: text, type, tag, text, ...)
_TAG_SPLIT = re.compile(r"(\n[\[(hgkx$vr])(\d+)(?=,)")


@dataclass
class _Sheets:
    """One file, read for a merge: inputs, header and the text of the sheets asked for, each
    record line with the newline in front of it (``"\nline1\nline2"``)."""

    inputs: dict[str, str]
    header: dict[str, str]
    sheets: dict[int, str]


def _read(path: Path, wanted: set[int] | None) -> _Sheets:
    """Inputs, header and sheets (``wanted``: their numbers, None: all) of a ``.synctex.gz``
    file. Whole-text regular expressions instead of a loop over the lines: a run's file has
    every page of the run, a merge usually needs a part of them."""
    with gzip.open(path, "rb") as f:
        text = "\n" + f.read().decode(*ENCODING)
    inputs = {tag: name for tag, name in _INPUT_LINE.findall(text)}
    markers = list(_MARKER.finditer(text))
    ends = [m.start() for m in markers[1:]] + [len(text)]  # each marker's part of the text
    header = dict(_HEADER_LINE.findall(text, 0, markers[0].start() if markers else len(text)))
    sheets: dict[int, str] = {}
    for m, end in zip(markers, ends, strict=True):
        if m.group(1) == "}":  # header lines after the content count as well, as in a line scan
            header.update(_HEADER_LINE.findall(text, m.end(), end))
            continue
        n = int(m.group(2))
        if wanted is None or n in wanted:
            sheets[n] = sheets.get(n, "") + _SKIPPED.sub("", text[m.end() : end])
    return _Sheets(inputs, header, sheets)


def parse(path: Path) -> ParsedSyncTex:
    """All inputs, header values and sheets of a ``.synctex.gz`` file."""
    read = _read(path, None)
    sheets = {n: body.split("\n")[1:] for n, body in read.sheets.items()}
    return ParsedSyncTex(read.inputs, read.header, sheets)


def merge(pages: Sequence[tuple[Path, int]], map_path: Callable[[str], str], out: Path) -> None:
    """Merged SyncTeX file for ``pages`` = (source ``.synctex.gz``, 0-based page index) in merged
    order. Input tags are renumbered globally in the order of their first use, paths mapped
    with ``map_path`` (keep ``/./``, S10), sheets renumbered, ``!`` offsets and the postamble
    recomputed. Each file is read once, for the sheets of its pages only."""
    wanted: dict[Path, set[int]] = {}
    for src, index in pages:
        wanted.setdefault(src, set()).add(index + 1)
    parsed = {src: _read(src, numbers) for src, numbers in wanted.items()}
    headers = {tuple(sorted(p.header.items())) for p in parsed.values()}
    if len(headers) != 1:
        raise SyncTexError(f"inconsistent SyncTeX headers: {sorted(headers)}")
    header = dict(next(iter(headers)))
    tags: dict[str, int] = {}
    local: dict[tuple[Path, str], str] = {}  # (file, its tag) -> merged tag; maps each input once
    blocks: list[tuple[int, bytes]] = []  # (merged sheet number, body)
    count = 0
    for n, (src, index) in enumerate(pages, start=1):
        p = parsed[src]
        body = p.sheets.get(index + 1)
        if body is None:
            raise SyncTexError(f"{src}: no sheet for page {index + 1}")
        parts = _TAG_SPLIT.split(body)
        used = parts[2::3]
        table: dict[str, str] = {}
        for tag in dict.fromkeys(used):  # first use first
            merged = local.get((src, tag))
            if merged is None:
                if tag not in p.inputs:  # tag 0: no input file (form xobjects)
                    merged = str(int(tag))
                else:
                    name = map_path(p.inputs[tag])
                    merged = str(tags.setdefault(name, len(tags) + 1))
                local[(src, tag)] = merged
            table[tag] = merged
        if any(old != new for old, new in table.items()):
            parts[2::3] = [table[tag] for tag in used]
            body = "".join(parts)
        count += body.count("\n") - body.count("\n]") - body.count("\n)")
        blocks.append((n, body.encode(*ENCODING)))
    head = ["SyncTeX Version:1", *(f"Input:{t}:{name}" for name, t in tags.items())]
    head += [f"{k}:{header[k]}" for k in HEADER_KEYS if k in header]
    data = bytearray("\n".join([*head, "Content:"]).encode(*ENCODING) + b"\n")
    last = 0

    def offset() -> None:  # "!<bytes since the previous ! line>" (S10)
        nonlocal last
        pos = len(data)
        data.extend(f"!{pos - last}\n".encode())
        last = pos

    for n, raw in blocks:
        offset()
        data.extend(f"{{{n}".encode())
        data.extend(raw)
        data.extend(b"\n")
        offset()
        data.extend(f"}}{n}\n".encode())
    offset()
    data.extend(f"Postamble:\nCount:{count}\n".encode())
    offset()
    data.extend(b"Post scriptum:\n")
    _write_gzip(out, bytes(data))
