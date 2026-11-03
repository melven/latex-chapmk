"""Aux files (PLAN §6.7): statements and their classes, main-aux segment slices, the
canonical main aux, structural lines, bookmark records.

Derived list files (.toc, .lof, ...) are not linked in Python: TeX expands their content when
writing them (e.g. ``\\protected@file@percent``) and aux macros like ``\\babel@aux`` add entries,
so every run writes complete list files from the aux files it read (M3).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

_SEG_START = re.compile(r"^\\chapmk@entry\{([UG]\d+)\}")
_SEG_END = re.compile(r"^\\chapmk@(entry|gexit|unit)\{")
_BKM = re.compile(r"^\\BKM@entry\{(.*)\}\{([0-9A-Fa-f]*)\}\s*$")


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()


def segment_slices(main_aux_lines: list[str]) -> dict[str, list[str]]:
    """Lines written to the main aux while each segment was current (S5, S8).

    A slice starts with the segment's ``\\chapmk@entry`` record and ends before the next
    ``\\chapmk@entry``/``\\chapmk@gexit``/``\\chapmk@unit`` record (all written immediately).
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


def statements(lines: Iterable[str]) -> list[str]:
    """Join aux lines into brace-balanced statements (``\\@setckpt`` and longtable's
    ``\\LT@`` records span several lines, S8). Escaped braces do not count."""
    out: list[str] = []
    pending: list[str] = []
    depth = 0
    for line in lines:
        pending.append(line)
        depth += _brace_balance(line)
        if depth <= 0:
            out.append("\n".join(pending))
            pending, depth = [], 0
    if pending:
        out.append("\n".join(pending))
    return out


def _brace_balance(line: str) -> int:
    balance, i = 0, 0
    while i < len(line):
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            balance += 1
        elif c == "}":
            balance -= 1
        i += 1
    return balance


# Statement classes (§6.7.2)
RECORD = "record"  # chapmk records
STRUCTURAL = "structural"  # constant per document or bookkeeping
LABEL = "label"  # \newlabel: export
LIST = "list"  # \@writefile: list contribution
CKPT = "ckpt"  # \@setckpt: exit state
CITE = "cite"  # \abx@aux@cite/segm: citation (-> .bcf)
BACKREF = "backref"  # \abx@aux@backref: citing page (read by the bibliography)
BIBDATA = "bibdata"  # other keyed biblatex data: merged per key
BOOKMARK = "bookmark"  # \BKM@entry: merge only
SELF = "self"  # data the writing segment reads back (pgf marks, longtable widths)
EQP = "eqp"  # eqparbox widths per tag (end of document)
AGGREGATE = "aggregate"  # OR over typeset segments (KOMA autodot)
LISTDATA = "listdata"  # written while typesetting lists (KOMA tocbasic widths)
ABSPAGE = "abspage"  # \@abspage@last: rewritten to the merged page count
GLOBAL = "global"  # unknown: a change dirties everything

_CLASSES: list[tuple[str, re.Pattern[str]]] = [
    (RECORD, re.compile(r"^\\chapmk@")),
    (
        STRUCTURAL,
        re.compile(
            r"^\\(relax\b|providecommand|babel@aux\b|@input\{|catcode\b|selectlanguage\b"
            r"|@nameuse\{bbl@beforestart\}|abx@aux@(refcontext|read@bbl@mdfivesum|read@bblrerun)\b)"
        ),
    ),
    (LABEL, re.compile(r"^\\newlabel\{")),
    (LIST, re.compile(r"^\\@writefile\{")),
    (CKPT, re.compile(r"^\\@setckpt\{")),
    (CITE, re.compile(r"^\\abx@aux@(cite|segm)\{")),
    (BACKREF, re.compile(r"^\\abx@aux@backref\{")),
    (BIBDATA, re.compile(r"^\\abx@aux@")),
    (BOOKMARK, re.compile(r"^\\BKM@entry\{")),
    (SELF, re.compile(r"^\\(pgfsyspdfmark\s*\{|gdef\s*\\LT@[ivxlcdm]+\s*\{)")),
    (EQP, re.compile(r"^\\expandafter\\gdef\\csname eqp@")),
    (AGGREGATE, re.compile(r"^\\global\\csname @altsecnumformattrue\\endcsname")),
    (LISTDATA, re.compile(r"^\\global\\@namedef\{scr@dte@[A-Za-z]+@lastmaxnumwidth\}")),
    (ABSPAGE, re.compile(r"^\\gdef\s*\\@abspage@last\{")),
]
#: classes of a unit's main-aux slice that belong to the unit (taken from its committed run);
#: biblatex data there is written at citation time (e.g. ``\\abx@aux@category``)
UNIT_CONTENT = (CITE, BACKREF, BIBDATA, BOOKMARK, SELF)


def classify(stmt: str) -> str:
    """Class of an aux statement (§6.7.2); unknown statements are :data:`GLOBAL`."""
    for name, pattern in _CLASSES:
        if pattern.match(stmt):
            return name
    return GLOBAL


def command_name(stmt: str) -> str:
    """The leading control sequence of a statement (for warnings)."""
    m = re.match(r"\\([A-Za-z@]+|.)", stmt)
    return f"\\{m.group(1)}" if m else stmt[:20]


_ABX_INSTCOUNT = re.compile(r"^(\\abx@aux@number)\{[^{}]*\}")


def normalize_statement(stmt: str) -> str:
    """A statement without run-local parts: biblatex's ``\\c@instcount`` (first argument of
    ``\\abx@aux@number``) numbers citation instances of a run, it is not data."""
    return _ABX_INSTCOUNT.sub(r"\1{}", stmt)


def statement_key(stmt: str) -> str:
    """A keyed statement without its last brace group (``\\abx@aux@defaultrefcontext{0}{k}``,
    ``\\expandafter\\gdef\\csname eqp@this@T\\endcsname``); run-local parts are dropped."""
    body = normalize_statement(stmt).rstrip()
    if not body.endswith("}"):
        return body
    depth = 0
    for i in range(len(body) - 1, -1, -1):
        if body[i] == "}" and (i == 0 or body[i - 1] != "\\"):
            depth += 1
        elif body[i] == "{" and (i == 0 or body[i - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return body[:i]
    return body


def run_input_main_aux(stmts: Sequence[str], excluded: set[str]) -> list[str]:
    """The canonical main aux as input of a run that excludes the unit segments ``excluded``:
    without their citations. biblatex compares the citations of the previous run with the
    current ones; citations of units the run does not compile would count as removed and
    suppress e.g. the ``defernumbers`` data (M4)."""
    return [
        s
        for seg, s in zip(segment_of_statements(stmts), stmts, strict=True)
        if not (seg in excluded and classify(s) == CITE)
    ]


def segment_of_statements(stmts: Sequence[str]) -> list[str | None]:
    """The segment each statement was written in (None outside slices), as in
    :func:`segment_slices`; the ``\\chapmk@entry`` statement itself belongs to its slice."""
    out: list[str | None] = []
    current: str | None = None
    for stmt in stmts:
        m = _SEG_START.match(stmt)
        if m:
            current = m.group(1)
        elif _SEG_END.match(stmt):
            current = None
        out.append(current)
    return out


def canonical_main_aux(
    run: Sequence[str],
    old: Sequence[str],
    keep_old: set[str],
    aggregates: Sequence[str],
    pages: int,
) -> list[str]:
    """The canonical main aux (§6.7.2) from the statements of the latest run's main aux:

    - slices of the segments in ``keep_old`` (not compiled in that run) get their
      :data:`UNIT_CONTENT` statements from the old canonical main aux;
    - keyed data outside unit slices (:data:`EQP`, :data:`BIBDATA`, e.g. eqparbox widths and
      ``defernumbers`` numbers at the end of the document) is merged per key, the run's values
      winning;
    - the :data:`AGGREGATE` statements are replaced by ``aggregates``;
    - ``\\@abspage@last`` is set to ``pages`` (the merged page count).
    """
    old_content: dict[str, list[str]] = {}
    old_segs = segment_of_statements(old)
    run_segs = segment_of_statements(run)
    for seg, stmt in zip(old_segs, old, strict=True):
        if seg in keep_old and classify(stmt) in UNIT_CONTENT:
            old_content.setdefault(seg, []).append(stmt)

    def keyed(seg: str | None, stmt: str) -> bool:
        return not (seg or "").startswith("U") and classify(stmt) in (EQP, BIBDATA)

    run_keys = {statement_key(s) for seg, s in zip(run_segs, run, strict=True) if keyed(seg, s)}
    carried = [
        s
        for seg, s in zip(old_segs, old, strict=True)
        if keyed(seg, s) and statement_key(s) not in run_keys
    ]
    out: list[str] = []
    tail: list[str] = []
    for seg, stmt in zip(run_segs, run, strict=True):
        kind = classify(stmt)
        if kind == AGGREGATE:
            continue
        if kind == ABSPAGE:
            tail.append(f"\\gdef \\@abspage@last{{{pages}}}")
            continue
        if seg in keep_old and kind in UNIT_CONTENT:
            continue
        out.append(stmt)
        if seg in keep_old and _SEG_START.match(stmt):
            out += old_content.get(seg, [])
    return out + carried + list(dict.fromkeys(aggregates)) + tail


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
    """``\\chapmk@bkmlevels{id=level,...}`` of a run's main aux (S6)."""
    levels: dict[int, int] = {}
    for line in main_aux_lines:
        m = re.match(r"^\\chapmk@bkmlevels\{(.*)\}\s*$", line)
        if m:
            for item in m.group(1).split(","):
                if "=" in item:
                    k, v = item.split("=")
                    levels[int(k)] = int(v)
    return levels
