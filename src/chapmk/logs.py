"""TeX log handling (PLAN §6.13): path mapping and error extraction."""

from __future__ import annotations

import re
from collections.abc import Sequence

from chapmk.texsource import text_lines

_FILE_LINE_ERROR = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+): (?P<msg>.*)$")


def map_paths(text: str, mapping: Sequence[tuple[str, str]]) -> str:
    """Replace build-path prefixes by user paths (e.g. shadow tree → source directory)."""
    for old, new in mapping:
        text = text.replace(old, new)
    return text


#: lines that only say that TeX stopped; the cause is an earlier error
_GENERIC_ERRORS = ("! Emergency stop.", "!  ==> Fatal error occurred")


def _errors(text: str) -> list[str]:
    return [
        line.rstrip()
        for line in text_lines(text)
        if line.startswith("! ") or _FILE_LINE_ERROR.match(line)
    ]


def first_error(log: str, output: str = "") -> str | None:
    """First error of a TeX run: a ``file:line: message`` line (``-file-line-error``) or a
    ``! message`` line, whichever comes first in the log. If the log has only a generic stop
    (``! Emergency stop.``), the first specific error of the terminal ``output`` is taken:
    an error before the log was opened, e.g. a file on the command line that does not exist
    (``! I can't find file `mylatexformat.ltx'.``), is only written there."""
    errors = _errors(log)
    specific = [e for e in errors if not e.startswith(_GENERIC_ERRORS)]
    if specific:
        return specific[0]
    from_output = [e for e in _errors(output) if not e.startswith(_GENERIC_ERRORS)]
    if from_output:
        return from_output[0]
    return errors[0] if errors else None


def short_list(items: Sequence[str], limit: int = 3) -> str:
    """``a, b, c, ... (+12 more)``: at most ``limit`` items of a list in a message."""
    shown = ", ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown}, ... (+{len(items) - limit} more)"
