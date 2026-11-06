"""TeX log handling (design §6.13): path mapping, error extraction, the composed log."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
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


# --- composed log (§6.13) ---------------------------------------------------------------------

#: start of a segment's slice in a run log (chapmk.sty, ``\wlog``: a line of its own)
SEGMENT_MARKER = "chapmk-segment: "
#: marker after the last page (``enddocument/afterlastpage``): the tail follows
END_MARKER = "end"
_OUTPUT_WRITTEN = re.compile(r"^Output written on .*$", re.MULTILINE)


def split_segments(text: str) -> tuple[str, dict[str, str], str] | None:
    """A run log split at the segment markers: the head (before the first marker), the text of
    each segment (the first slice of a marker seen twice), the tail (after the end marker).
    None without an end marker (a log from an older chapmk, or a run that stopped early)."""
    head = ""
    slices: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in split_lines(text):
        if not line.startswith(SEGMENT_MARKER):
            lines.append(line)
            continue
        chunk, lines = "".join(lines), []
        if current is None:
            head = chunk
        else:
            slices.setdefault(current, chunk)
        current = line[len(SEGMENT_MARKER) :].strip()
    if current != END_MARKER:
        return None
    return head, slices, "".join(lines)


def _open_parentheses(text: str) -> int:
    """Parentheses opened and not closed (file opens and others, as log parsers count them)."""
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
    return depth


def format_preamble(fmt_log: str) -> str:
    """The preamble part of the format build's log (package loading and its messages): the
    lines after the command line (``**...``) up to the dump, with the files still open at the
    dump closed, so that later messages are attributed to the right file."""
    lines = split_lines(fmt_log)
    start = next((n + 1 for n, line in enumerate(lines) if line.startswith("**")), None)
    if start is None:
        return ""
    body = []
    for line in lines[start:]:
        if line.startswith("Beginning to dump on file"):
            break
        body.append(line)
    text = "".join(body)
    if text and not text.endswith("\n"):
        text += "\n"
    depth = _open_parentheses(text)
    return text + (")" * depth + "\n" if depth else "")


def _with_preamble(head: str, preamble: str) -> str:
    """``preamble`` inserted after the line that opens the main file (the first line after the
    command line that starts with ``(``), where a plain run loads the preamble's packages."""
    if not preamble:
        return head
    lines = split_lines(head)
    command = next((n for n, line in enumerate(lines) if line.startswith("**")), -1)
    at = next(
        (n + 1 for n, line in enumerate(lines) if n > command and line.startswith("(")),
        len(lines),
    )
    if at and not lines[at - 1].endswith("\n"):
        lines[at - 1] += "\n"
    return "".join(lines[:at]) + preamble + "".join(lines[at:])


def compose_log(
    logs: Mapping[str, str],
    sources: Sequence[tuple[str, str]],
    preamble: str = "",
    output: str | None = None,
) -> str | None:
    """One log in the order of a plain pdflatex run (§6.13): the head of the run of the first
    segment (with ``preamble``, the format build's part, after the main file is opened), each
    segment's slice from the run that produced it (``sources``: ``(segment, run)`` in document
    order), the tail of the last segment's run with its ``Output written on`` line replaced by
    ``output``. None if a run log lacks the markers or a segment's slice."""
    if not sources:
        return None
    parts: dict[str, tuple[str, dict[str, str], str]] = {}
    for _, run in sources:
        if run not in parts:
            split = split_segments(logs.get(run, ""))
            if split is None:
                return None
            parts[run] = split
    body = []
    for seg, run in sources:
        text = parts[run][1].get(seg)
        if text is None:
            return None
        body.append(text)
    tail = parts[sources[-1][1]][2]
    if output is not None:
        tail = _OUTPUT_WRITTEN.sub(lambda _: output, tail, count=1)
    return _with_preamble(parts[sources[0][1]][0], preamble) + "".join(body) + tail
