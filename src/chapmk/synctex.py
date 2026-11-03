"""SyncTeX files (PLAN §6.12, S10): read, write with recomputed offsets, map paths, merge."""

from __future__ import annotations

import gzip
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from chapmk.errors import ChapmkError

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
    data = serialise(lines)
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
_TAGGED = re.compile(r"^([\[(hgkx$vr])(\d+),")
_SHEET_OPEN = re.compile(r"^\{(\d+)$")
_SHEET_CLOSE = re.compile(r"^\}(\d+)$")


class SyncTexError(ChapmkError):
    """SyncTeX files cannot be merged (inconsistent headers, missing sheets)."""


@dataclass
class ParsedSyncTex:
    """Input tags, header values and sheets (records without ``!`` lines) of one file."""

    inputs: dict[str, str]
    header: dict[str, str]
    sheets: dict[int, list[str]]


def parse(path: Path) -> ParsedSyncTex:
    inputs: dict[str, str] = {}
    header: dict[str, str] = {}
    sheets: dict[int, list[str]] = {}
    current: list[str] | None = None
    for line in read_lines(path):
        if line.startswith("Input:"):
            _, tag, name = line.split(":", 2)
            inputs[tag] = name
        elif (m := _SHEET_OPEN.match(line)) is not None:
            current = sheets.setdefault(int(m.group(1)), [])
        elif _SHEET_CLOSE.match(line):
            current = None
        elif current is not None:
            if line and not line.startswith("!"):
                current.append(line)
        elif ":" in line and line.split(":", 1)[0] in HEADER_KEYS:
            key, value = line.split(":", 1)
            header[key] = value
    return ParsedSyncTex(inputs, header, sheets)


def merge(pages: Sequence[tuple[Path, int]], map_path: Callable[[str], str], out: Path) -> None:
    """Merged SyncTeX file for ``pages`` = (source ``.synctex.gz``, 0-based page index) in merged
    order. Input tags are renumbered globally, paths mapped with ``map_path`` (keep ``/./``,
    S10), sheets renumbered, ``!`` offsets and the postamble recomputed."""
    parsed: dict[Path, ParsedSyncTex] = {}
    for src, _ in pages:
        if src not in parsed:
            parsed[src] = parse(src)
    headers = {tuple(sorted(p.header.items())) for p in parsed.values()}
    if len(headers) != 1:
        raise SyncTexError(f"inconsistent SyncTeX headers: {sorted(headers)}")
    header = dict(next(iter(headers)))
    tags: dict[str, int] = {}
    local: dict[tuple[Path, str], int] = {}  # (file, its tag) -> merged tag; maps each input once
    body: list[str] = []
    count = 0
    for n, (src, index) in enumerate(pages, start=1):
        p = parsed[src]
        sheet = p.sheets.get(index + 1)
        if sheet is None:
            raise SyncTexError(f"{src}: no sheet for page {index + 1}")
        body += ["!0", f"{{{n}"]
        for line in sheet:
            m = _TAGGED.match(line)
            if m:
                key = (src, m.group(2))
                tag = local.get(key)
                if tag is None:
                    if m.group(2) not in p.inputs:  # tag 0: no input file (form xobjects)
                        tag = local[key] = int(m.group(2))
                    else:
                        name = map_path(p.inputs[m.group(2)])
                        tag = local[key] = tags.setdefault(name, len(tags) + 1)
                line = f"{m.group(1)}{tag}," + line[m.end() :]
            if not line.startswith(("]", ")")):
                count += 1
            body.append(line)
        body += ["!0", f"}}{n}"]
    lines = ["SyncTeX Version:1", *(f"Input:{t}:{name}" for name, t in tags.items())]
    lines += [f"{k}:{header[k]}" for k in HEADER_KEYS if k in header]
    lines += ["Content:", *body, "!0", "Postamble:", f"Count:{count}", "!0", "Post scriptum:"]
    write_lines(out, lines)
