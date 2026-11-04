"""TeX log handling (PLAN §6.13): path mapping and error extraction."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from chapmk.files import read_log
from chapmk.texsource import text_lines

_FILE_LINE_ERROR = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+): (?P<msg>.*)$")


def map_paths(text: str, mapping: Sequence[tuple[str, str]]) -> str:
    """Replace build-path prefixes by user paths (e.g. shadow tree → source directory)."""
    for old, new in mapping:
        text = text.replace(old, new)
    return text


def first_error(log: str) -> str | None:
    """First error of a TeX log: a ``file:line: message`` line (``-file-line-error``) or a
    ``! message`` line, whichever comes first."""
    for line in text_lines(log):
        if line.startswith("! ") or _FILE_LINE_ERROR.match(line):
            return line.rstrip()
    return None


def run_error(log: Path, output: str, mapping: Sequence[tuple[str, str]]) -> str | None:
    """First error of a failed TeX run, path-mapped: from its log file, or from the program
    output if the run wrote no log."""
    text = read_log(log) if log.is_file() else output
    return first_error(map_paths(text, mapping))


def short_list(items: Sequence[str], limit: int = 3) -> str:
    """``a, b, c, ... (+12 more)``: at most ``limit`` items of a list in a message."""
    shown = ", ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown}, ... (+{len(items) - limit} more)"
