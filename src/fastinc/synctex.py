"""SyncTeX files (PLAN §6.12, S10): reading, writing with recomputed offsets, path mapping.

The full merge of several runs follows in M3; this module holds the shared file handling.
"""

from __future__ import annotations

import gzip
from collections.abc import Sequence
from pathlib import Path

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
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as f:
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
