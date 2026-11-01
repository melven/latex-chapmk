"""Lint for assumption A1 (PLAN §6.8.4): state changes in unit bodies that leak to later units.

A unit with a hit is *global*: whenever it is recompiled, all later units are dirty.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from fastinc.texsource import LineIndex, strip_comments

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
) -> list[LintHit]:
    """Hits in the TeX sources among ``names`` (relative to ``source_dir``)."""
    hits: list[LintHit] = []
    for name in names:
        path = source_dir / name
        if Path(name).suffix in LINT_SUFFIXES and path.is_file():
            text = path.read_bytes().decode("utf-8", "surrogateescape")
            hits += lint_text(text, name, allow, verbatim, shortverb)
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
