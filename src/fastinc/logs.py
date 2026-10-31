"""TeX log handling (PLAN §6.13): path mapping and error extraction."""

from __future__ import annotations

import re
from collections.abc import Sequence

_FILE_LINE_ERROR = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+): (?P<msg>.*)$")


def map_paths(text: str, mapping: Sequence[tuple[str, str]]) -> str:
    """Replace build-path prefixes by user paths (e.g. shadow tree → source directory)."""
    for old, new in mapping:
        text = text.replace(old, new)
    return text


def first_error(log: str) -> str | None:
    """First error of a TeX log: a ``file:line: message`` line (``-file-line-error``) or a
    ``! message`` line, whichever comes first."""
    for line in log.splitlines():
        if line.startswith("! ") or _FILE_LINE_ERROR.match(line):
            return line.rstrip()
    return None


def rerun_requested(log: str) -> bool:
    """Whether the log asks for another run (LaTeX, hyperref, biblatex, longtable, ...)."""
    return bool(
        re.search(
            r"(Rerun to get|Please rerun LaTeX|Label\(s\) may have changed|rerun LaTeX)",
            log,
            re.IGNORECASE,
        )
    )
