"""TeX log handling (design §6.13): path mapping and error extraction."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from chapmk.files import read_log
from chapmk.texsource import split_lines, text_lines

#: ``file:line: message``; the file may start with a drive letter (Windows: TeX gets absolute
#: paths, and error lines are mapped to the user's main file, ``D:\\doc\\main.tex:3: ...``)
_FILE_LINE_ERROR = re.compile(
    r"^(?P<file>(?:[A-Za-z]:[\\/])?[^\s:][^:]*):(?P<line>\d+): (?P<msg>.*)$"
)


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
    (``! I can't find file `mylatexformat.ltx'.``), is only written there. Without any error
    line, the last line of ``output`` (e.g. a message of the distribution: TeX did not run)."""
    errors = _errors(log)
    specific = [e for e in errors if not e.startswith(_GENERIC_ERRORS)]
    if specific:
        return specific[0]
    from_output = [e for e in _errors(output) if not e.startswith(_GENERIC_ERRORS)]
    if from_output:
        return from_output[0]
    if errors:
        return errors[0]
    tail = [line.strip() for line in text_lines(output) if line.strip()]
    return tail[-1] if tail else None


def run_error(log: Path, output: str, mapping: Sequence[tuple[str, str]]) -> str | None:
    """First error of a failed TeX run, path-mapped: from its log file, or from the program
    output if the run wrote no log; behind a generic stop in the log, the specific error of
    the program output (:func:`first_error`)."""
    text = read_log(log) if log.is_file() else output
    return first_error(map_paths(text, mapping), map_paths(output, mapping))


def short_list(items: Sequence[str], limit: int = 3) -> str:
    """``a, b, c, ... (+12 more)``: at most ``limit`` items of a list in a message."""
    shown = ", ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown}, ... (+{len(items) - limit} more)"


#: the first line of a TeX log
_BANNER = re.compile(r"^This is \S*TeX, Version")


def printed_log(text: str) -> str:
    """The published log as ``--print-log`` writes it (§6.13): the banner line only in the first
    run's log. VS Code LaTeX Workshop parses only the build command's output and keeps the text
    after the last banner (latexmk prints several runs), so it would see only the last run."""
    seen = False
    lines = []
    for line in split_lines(text):
        if _BANNER.match(line):
            if seen:
                continue
            seen = True
        lines.append(line)
    return "".join(lines)
