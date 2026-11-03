"""Lint for assumption A1 (PLAN §6.8.4): state changes in unit bodies that leak to later units.

A unit with a hit is *global*: whenever it is recompiled, all later units are dirty.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chapmk
from chapmk.texsource import LineIndex, strip_comments

#: hits only outside an explicit group
LOCAL_COMMANDS = frozenset(
    [
        "def",
        "edef",
        "let",
        "newcommand",
        "renewcommand",
        "providecommand",
        "DeclareRobustCommand",
        "NewDocumentCommand",
        "RenewDocumentCommand",
        "NewCommandCopy",
        "newenvironment",
        "renewenvironment",
        "setlength",
        "addtolength",
        "captionsetup",
        "sisetup",
        "lstset",
        "tikzset",
        "definecolor",
        "makeatletter",
        "catcode",
        "ExplSyntaxOn",
    ]
)
#: always hits
GLOBAL_COMMANDS = frozenset(
    [
        "gdef",
        "xdef",
        "global",
        "newcounter",
        "newlength",
        "newcount",
        "newdimen",
        "newskip",
        "newtoks",
        "newtheorem",
        "counterwithin",
        "counterwithout",
        "pagenumbering",
        "pagestyle",
        "appendix",
        "frontmatter",
        "mainmatter",
        "backmatter",
        "selectlanguage",
        "hypersetup",
        "KOMAoptions",
        "usetikzlibrary",
        "DeclareSIUnit",
        "DeclareMathOperator",
    ]
)
#: source files linted: TeX sources, not packages or data
LINT_SUFFIXES = (".tex", ".ltx")
#: environments whose content is not scanned
VERBATIM_ENVIRONMENTS = frozenset(
    [
        "verbatim",
        "verbatim*",
        "Verbatim",
        "BVerbatim",
        "LVerbatim",
        "lstlisting",
        "minted",
        "comment",
        "filecontents",
        "filecontents*",
    ]
)

_TOKEN = re.compile(r"\\([A-Za-z@]+)|\\(.)|([{}\[\]])|(\S)", re.DOTALL)
_ENV_ARG = re.compile(r"\s*\{([^{}]*)\}")
_NEXT_CS = re.compile(r"\s*\\([A-Za-z@]+)")


@dataclass(frozen=True)
class LintHit:
    """A command in a unit body that changes state beyond the unit (A1)."""

    file: str
    line: int
    command: str
    is_global: bool  # from the global list (or \global prefix); else outside a group

    def message(self) -> str:
        if self.is_global:
            advice = "it has a global effect; move it to the preamble"
        else:
            advice = "outside a group; wrap it in a group or environment"
        return (
            f"{self.file}:{self.line}: {self.command} in a unit body: {advice} "
            "(the unit is treated as global: later units are recompiled with it)"
        )


def lint_files(
    source_dir: Path,
    names: Iterable[str],
    allow: Iterable[str] = (),
    verbatim: Iterable[str] = (),
    shortverb: Iterable[str] = (),
    cache: dict[str, list[list[Any]]] | None = None,
) -> list[LintHit]:
    """Hits in the TeX sources among ``names`` (relative to ``source_dir``). ``cache`` maps a
    digest of file name, content and options to the file's hits (as lists, JSON-ready);
    entries are added for linted files."""
    options = json.dumps([chapmk.__version__, sorted(allow), sorted(verbatim), sorted(shortverb)])
    hits: list[LintHit] = []
    for name in names:
        path = source_dir / name
        if Path(name).suffix in LINT_SUFFIXES and path.is_file():
            data = path.read_bytes()
            key = hashlib.sha256(
                name.encode() + b"\0" + options.encode() + b"\0" + data
            ).hexdigest()
            if cache is not None and key in cache:
                hits += [LintHit(*h) for h in cache[key]]
                continue
            text = data.decode("utf-8", "surrogateescape")
            found = lint_text(text, name, allow, verbatim, shortverb)
            if cache is not None:
                cache[key] = [[h.file, h.line, h.command, h.is_global] for h in found]
            hits += found
    return hits


def lint_text(
    text: str,
    file: str,
    allow: Iterable[str] = (),
    verbatim: Iterable[str] = (),
    shortverb: Iterable[str] = (),
) -> list[LintHit]:
    """Hits in one source text (comments stripped; content of verbatim environments, also
    ``verbatim`` from the config, and of ``\\verb`` and the ``shortverb`` characters
    (``lint.shortverb``, e.g. ``|``) skipped)."""
    allowed = {a.lstrip("\\") for a in allow}
    verbatim_envs = VERBATIM_ENVIRONMENTS | set(verbatim)
    short = set(shortverb)
    text = strip_comments(text)
    lines = LineIndex(text)
    hits: list[LintHit] = []
    stack: list[str] = []  # "env:<name>", "group", "brace", "arg"
    prev = "other"  # kind of the previous token: "cs", "close" or "other"
    pos = 0
    while True:
        m = _TOKEN.search(text, pos)
        if m is None:
            break
        pos = m.end()
        word, symbol, delim = m.group(1), m.group(2), m.group(3)
        if word is not None:
            if word in ("begin", "end"):
                arg = _ENV_ARG.match(text, pos)
                if arg is not None:
                    pos = arg.end()
                    name = arg.group(1)
                    if word == "begin" and name in verbatim_envs:
                        end = text.find(f"\\end{{{name}}}", pos)
                        pos = len(text) if end < 0 else end
                    elif word == "begin":
                        stack.append(f"env:{name}")
                    else:
                        _pop(stack, f"env:{name}")
                prev = "close"
                continue
            if word in ("begingroup", "bgroup"):
                stack.append("group")
            elif word in ("endgroup", "egroup"):
                _pop(stack, "group")
            elif word in ("verb", "lstinline") and pos < len(text):
                delim_char = text[pos]
                if delim_char not in "{[":
                    end = text.find(delim_char, pos + 1)
                    pos = len(text) if end < 0 else end + 1
                    prev = "other"
                    continue
            elif word not in allowed:
                hit = _hit(word, text, pos, stack)
                if hit is not None:
                    hits.append(LintHit(file, lines.line_of(m.start()), *hit))
            prev = "cs"
        elif symbol is not None:
            prev = "other"
        elif delim == "{":
            stack.append("arg" if prev in ("cs", "close") else "brace")
            prev = "other"
        elif delim == "}":
            _pop(stack, None)
            prev = "close"
        elif delim == "]":
            prev = "close"
        else:
            if m.group(4) in short:  # short verbatim up to the same character on the line
                end = text.find(m.group(4), pos)
                newline = text.find("\n", pos)
                if end >= 0 and (newline < 0 or end < newline):
                    pos = end + 1
            prev = "other"
    return hits


def _hit(word: str, text: str, pos: int, stack: list[str]) -> tuple[str, bool] | None:
    if word == "global":
        nxt = _NEXT_CS.match(text, pos)
        if nxt is not None and nxt.group(1) in LOCAL_COMMANDS:
            return f"\\global\\{nxt.group(1)}", True
        return "\\global", True
    if word in GLOBAL_COMMANDS:
        return f"\\{word}", True
    if word in LOCAL_COMMANDS and not any(kind != "arg" for kind in stack):
        if _prefixed_by_global(text, pos - len(word) - 1):
            return None  # reported at the \global
        return f"\\{word}", False
    return None


def _prefixed_by_global(text: str, start: int) -> bool:
    return re.search(r"\\global\s*$", text[max(0, start - 20) : start]) is not None


def _pop(stack: list[str], kind: str | None) -> None:
    """Close the innermost group of ``kind`` (any brace group for None); tolerate mismatches."""
    for i in range(len(stack) - 1, -1, -1):
        if (kind is None and stack[i] in ("arg", "brace")) or stack[i] == kind:
            del stack[i:]
            return


#: glue commands that typeset a list starting with a chapter-level heading (book classes)
_PAGE_STARTERS = frozenset(
    {
        "printbibliography",
        "printnomenclature",
        "tableofcontents",
        "listoffigures",
        "listoftables",
        "printindex",
    }
)
_FIRST_CS = re.compile(r"\s*\\([A-Za-z@]+\*?)")
_CONTROL_WORD = re.compile(r"\\([A-Za-z@]+\*?)")


def _balanced(text: str) -> bool:
    """No group (``\\begingroup``/``\\bgroup``) or environment open at the end of ``text``."""
    groups = len(re.findall(r"\\(begingroup|bgroup)(?![A-Za-z@])", text)) - len(
        re.findall(r"\\(endgroup|egroup)(?![A-Za-z@])", text)
    )
    envs = len(re.findall(r"\\begin\s*\{", text)) - len(re.findall(r"\\end\s*\{", text))
    return groups == 0 and envs == 0


def glue_hints(
    main_name: str,
    lines: Sequence[str],
    begin_line: int,
    include_lines: list[int],
    glue_times: dict[str, float],
    headings: Iterable[str],
    threshold: float = 0.5,
) -> list[str]:
    """Advice for glue segments that take at least ``threshold`` seconds in every run
    (``glue_times``: seconds per ``G<k>``): such a block can move into an ``\\include``'d
    file without changing the output if it starts with a chapter-level heading (or a list
    command that typesets one), changes no state for later parts (A1 lint) and is a closed
    block (no group or environment open across its ends); it then is excluded from runs
    that do not need it. ``lines`` are the main file's lines, ``include_lines`` the line
    numbers of its ``\\include`` commands."""
    headings = set(headings)
    hints = []
    for seg, seconds in sorted(glue_times.items(), key=lambda x: int(x[0][1:])):
        if seconds < threshold:
            continue
        k = int(seg[1:])
        start = begin_line + 1 if k == 0 else include_lines[k - 1] + 1
        if k < len(include_lines):
            end = include_lines[k] - 1
        else:
            end = (
                next(
                    (i for i in range(start, len(lines) + 1) if "\\end{document}" in lines[i - 1]),
                    len(lines) + 1,
                )
                - 1
            )
        text = strip_comments("".join(lines[start - 1 : end]))
        m = _FIRST_CS.match(text)
        first = m.group(1) if m else None
        where = f"{main_name}:{start}-{end}: glue" + (f" (\\{first})" if first else "")
        # the movable part starts at the first chapter-level heading or list command; what
        # precedes it (e.g. \backmatter) stays in the main file
        split = next(
            (
                c
                for c in _CONTROL_WORD.finditer(text)
                if c.group(1) in headings or c.group(1) in _PAGE_STARTERS
            ),
            None,
        )
        if split is None:
            hints.append(
                f"{where} takes {seconds:.1f} s in every run; it has no chapter-level heading, "
                "so it stays glue"
            )
            continue
        name = split.group(1)
        moved, before = text[split.start() :], text[: split.start()]
        first_line = start + text.count("\n", 0, split.start())
        hits = lint_text(moved, main_name)
        if hits:
            reason = f"the part from line {first_line} contains {hits[0].command}"
        elif not (_balanced(moved) and _balanced(before)):
            reason = "a group or environment is open across its ends"
        else:
            keep = f" (lines {start}-{first_line - 1} stay)" if before.strip() else ""
            config = "" if name in headings else f' and chapmk.toml [units] heading = ["{name}"]'
            hints.append(
                f"{where} takes {seconds:.1f} s in every run; lines {first_line}-{end} "
                f"(from \\{name}) moved into an \\include'd file{config}{keep} are compiled "
                "only when needed (output unchanged)"
            )
            continue
        hints.append(f"{where} takes {seconds:.1f} s in every run; {reason}, so it stays glue")
    return hints
