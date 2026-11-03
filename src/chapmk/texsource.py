"""Lightweight scanning of LaTeX source text (no TeX execution).

Used by the project analysis (PLAN §6.1) and later by the lint (§6.8.4). The scanner knows
only what the driver needs: comments, braces, control words and their arguments. It does
not expand macros and does not know verbatim environments.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterator
from dataclasses import dataclass

_CONTROL_WORD = re.compile(r"\\([A-Za-z@]+\*?|[\s\S])")


def strip_comment(line: str) -> str:
    """Return ``line`` without its ``%`` comment. ``\\%`` is not a comment; the newline is kept."""
    i = 0
    while True:
        i = line.find("%", i)
        if i < 0:
            return line
        backslashes = 0
        j = i - 1
        while j >= 0 and line[j] == "\\":
            backslashes += 1
            j -= 1
        if backslashes % 2 == 0:
            end = "\n" if line.endswith("\n") else ""
            return line[:i] + end
        i += 1


def split_lines(text: str) -> list[str]:
    """Split ``text`` at ``\\n`` only, keeping line endings (``\\r\\n`` stays intact).

    Unlike :meth:`str.splitlines` this does not split at form feeds or Unicode line
    separators, so line numbers agree with TeX's.
    """
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def text_lines(text: str) -> list[str]:
    """Lines of a file TeX or a tool wrote (aux, log, ``.fls``, ``.bcf`` ...), without line
    endings: split at ``\n`` only, a trailing ``\r`` removed (C12). Unlike
    :meth:`str.splitlines`, form feeds and Unicode line separators (U+2028, common in
    copy-pasted titles) stay inside their line."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def strip_comments(text: str) -> str:
    """Strip comments from every line of ``text``; the line structure stays."""
    return "".join(strip_comment(line) for line in split_lines(text))


@dataclass(frozen=True)
class ControlSequence:
    """A control sequence found in comment-free text.

    ``name`` excludes the backslash and includes a trailing ``*`` for starred control words
    (``chapter*``). ``start``/``end`` are offsets in the scanned text, ``depth`` is the brace
    depth at ``start`` (0 = top level).
    """

    name: str
    start: int
    end: int
    depth: int


def control_sequences(text: str) -> Iterator[ControlSequence]:
    """Yield the control sequences of comment-free ``text`` with their brace depth."""
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            m = _CONTROL_WORD.match(text, i)
            if m is None:  # trailing backslash
                return
            yield ControlSequence(m.group(1), i, m.end(), depth)
            i = m.end()
        elif c == "{":
            depth += 1
            i += 1
        elif c == "}":
            depth = max(0, depth - 1)
            i += 1
        else:
            i += 1


def skip_space(text: str, pos: int) -> int:
    """Offset of the first non-whitespace character at or after ``pos``."""
    while pos < len(text) and text[pos] in " \t\r\n":
        pos += 1
    return pos


def read_group(text: str, pos: int) -> tuple[str, int] | None:
    """Read a ``{...}`` group starting at ``pos`` (after optional spaces).

    Returns ``(content, end offset)`` or ``None`` if there is no complete group.
    """
    pos = skip_space(text, pos)
    if pos >= len(text) or text[pos] != "{":
        return None
    depth = 0
    i = pos
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[pos + 1 : i], i + 1
        i += 1
    return None


def read_optional(text: str, pos: int) -> tuple[str | None, int]:
    """Read an optional ``[...]`` argument at ``pos``; returns ``(content or None, end)``."""
    p = skip_space(text, pos)
    if p >= len(text) or text[p] != "[":
        return None, pos
    depth = 0
    i = p
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "]" and depth == 0:
            return text[p + 1 : i], i + 1
        i += 1
    return None, pos


@dataclass(frozen=True)
class Macro:
    """A macro call with its optional and mandatory argument (both may be absent)."""

    name: str
    start: int
    end: int
    depth: int
    optional: str | None
    argument: str | None


def find_macros(text: str, names: set[str]) -> list[Macro]:
    """Find calls of the control words in ``names`` in comment-free ``text``.

    Each call is read as ``\\name[opt]{arg}``; missing parts are ``None``.
    """
    found: list[Macro] = []
    for cs in control_sequences(text):
        if cs.name not in names:
            continue
        opt, pos = read_optional(text, cs.end)
        group = read_group(text, pos)
        arg, end = (group[0], group[1]) if group else (None, pos)
        found.append(Macro(cs.name, cs.start, end, cs.depth, opt, arg))
    return found


class LineIndex:
    """Maps text offsets to 1-based line numbers."""

    def __init__(self, text: str) -> None:
        self._starts = [0] + [m.end() for m in re.finditer(r"\n", text)]

    def line_of(self, offset: int) -> int:
        """1-based line number containing ``offset``."""
        return bisect.bisect_right(self._starts, offset)


def depth_at_line_starts(lines: list[str]) -> list[int]:
    """Brace depth at the start of each line of comment-free ``lines`` (escaped braces ignored)."""
    depths: list[int] = []
    depth = 0
    for line in lines:
        depths.append(depth)
        i = 0
        while i < len(line):
            c = line[i]
            if c == "\\":
                i += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth = max(0, depth - 1)
            i += 1
    return depths


#: TeX's primitive conditionals (pdfTeX/e-TeX)
PRIMITIVE_CONDITIONALS = frozenset(
    [
        "if",
        "ifcat",
        "ifx",
        "ifnum",
        "ifdim",
        "ifodd",
        "ifcase",
        "ifvmode",
        "ifhmode",
        "ifmmode",
        "ifinner",
        "ifvoid",
        "ifhbox",
        "ifvbox",
        "ifeof",
        "iftrue",
        "iffalse",
        "ifdefined",
        "ifcsname",
        "iffontchar",
        "ifincsname",
        "ifpdfprimitive",
        "ifpdfabsnum",
        "ifpdfabsdim",
    ]
)
_WORD = re.compile(r"\\([A-Za-z@]+)")


def open_conditional_at_line_starts(lines: list[str]) -> list[int]:
    """For each line of comment-free ``lines``: the 1-based line of the outermost conditional
    that is still open at the line start (0 if none). Conditionals are TeX primitives and
    switches defined by ``\\newif`` in ``lines``; ``\\fi`` closes."""
    switches: set[str] = set()
    for line in lines:
        switches.update(m.group(1) for m in re.finditer(r"\\newif\s*\\(if[A-Za-z@]+)", line))
    out: list[int] = []
    stack: list[int] = []
    for lineno, line in enumerate(lines, start=1):
        out.append(stack[0] if stack else 0)
        after_newif = False
        for m in _WORD.finditer(line):
            name = m.group(1)
            if after_newif:
                after_newif = False
                continue
            if name == "newif":
                after_newif = True
            elif name in PRIMITIVE_CONDITIONALS or name in switches:
                stack.append(lineno)
            elif name == "fi" and stack:
                stack.pop()
    return out


def split_list(arg: str) -> list[str]:
    """Split a comma-separated macro argument (``a, b,c``) into stripped, non-empty items."""
    return [item.strip() for item in arg.split(",") if item.strip()]
