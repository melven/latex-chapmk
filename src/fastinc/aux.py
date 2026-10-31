"""Aux files (PLAN §6.7): main-aux segment slices, structural lines, bookmark records.

Derived list files (.toc, .lof, ...) are not linked in Python: TeX expands their content when
writing them (e.g. ``\\protected@file@percent``) and aux macros like ``\\babel@aux`` add entries,
so every run writes complete list files from the aux files it read (M3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SEG_START = re.compile(r"^\\fastinc@entry\{([UG]\d+)\}")
_SEG_END = re.compile(r"^\\fastinc@(entry|gexit|unit)\{")
_BKM = re.compile(r"^\\BKM@entry\{(.*)\}\{([0-9A-Fa-f]*)\}\s*$")


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()


def segment_slices(main_aux_lines: list[str]) -> dict[str, list[str]]:
    """Lines written to the main aux while each segment was current (S5, S8).

    A slice starts with the segment's ``\\fastinc@entry`` record and ends before the next
    ``\\fastinc@entry``/``\\fastinc@gexit``/``\\fastinc@unit`` record (all written immediately).
    """
    slices: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in main_aux_lines:
        m = _SEG_START.match(line)
        if m:
            current = slices.setdefault(m.group(1), [])
            current.append(line)
            continue
        if _SEG_END.match(line):
            current = None
            continue
        if current is not None:
            current.append(line)
    return slices


_STRUCTURAL = re.compile(r"^\\(relax\b|providecommand)")


def content_lines(lines: list[str]) -> list[str]:
    """Aux lines without structural ones (``\\relax``, ``\\providecommand``): packages write
    these once per run into whichever aux file comes first, so they depend on the selection
    of a run, not on the document (S8, M3)."""
    return [line for line in lines if not _STRUCTURAL.match(line)]


@dataclass(frozen=True)
class Bookmark:
    """A ``\\BKM@entry`` record (S6): run-local id, open flag, destination, title bytes."""

    id: int
    open: bool
    dest: str
    title: bytes


def tex_octal_bytes(data: bytes) -> bytes:
    """Decode TeX PDF-string escapes (``\\ooo`` octal, ``\\x``) to raw bytes."""
    out = bytearray()
    i = 0
    while i < len(data):
        c = data[i]
        if c == 0x5C and data[i + 1 : i + 4].isdigit() and len(data[i + 1 : i + 4]) == 3:
            out.append(int(data[i + 1 : i + 4], 8))
            i += 4
        elif c == 0x5C and i + 1 < len(data):
            out.append(data[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    return bytes(out)


def parse_bookmark(line: str) -> Bookmark | None:
    m = _BKM.match(line)
    if not m:
        return None
    keys: dict[str, str] = {}
    for item in re.finditer(r"(\w+)(?:=\{([^}]*)\}|=([^,]*))?", m.group(1)):
        keys[item.group(1)] = item.group(2) if item.group(2) is not None else item.group(3) or ""
    dest = bytes.fromhex(keys.get("dest", "")).decode("latin-1")
    title = tex_octal_bytes(bytes.fromhex(m.group(2)))
    return Bookmark(int(keys["id"]), "open" in keys, dest, title)


def bookmark_levels(main_aux_lines: list[str]) -> dict[int, int]:
    """``\\fastinc@bkmlevels{id=level,...}`` of a run's main aux (S6)."""
    levels: dict[int, int] = {}
    for line in main_aux_lines:
        m = re.match(r"^\\fastinc@bkmlevels\{(.*)\}\s*$", line)
        if m:
            for item in m.group(1).split(","):
                if "=" in item:
                    k, v = item.split("=")
                    levels[int(k)] = int(v)
    return levels
