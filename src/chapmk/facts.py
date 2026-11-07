"""Document facts shared by the analysis, the builder, the runs and the shadow tree (D4):
one table each, so the static and the runtime checks cannot disagree.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Packages that force full mode (design §1): checked in the preamble (analysis) and, as
#: ``<name>.sty``, in the ``.fls`` of the format build and of every run (also when a class or
#: another package loads them).
UNSUPPORTED_PACKAGES = frozenset(
    {"glossaries", "glossaries-extra", "imakeidx", "makeidx", "minted"}
)

#: First commands that start a compilation unit (A5, §6.1 step 5). Config adds
#: ``units.heading`` (treated like these).
UNIT_HEADINGS: tuple[str, ...] = (
    "chapter",
    "chapter*",
    "addchap",
    "addchap*",
    "part",
    "part*",
    "addpart",
    "addpart*",
)

#: Top-level headings of article-like classes (no ``\\chapter``): they start a compilation unit
#: only if no include starts with one of :data:`UNIT_HEADINGS`.
SECTION_HEADINGS: tuple[str, ...] = ("section", "section*", "addsec", "addsec*")

#: List files every document may have (``\\@starttoc``); a document's own list files (``L``
#: records, e.g. ``.loa``) are added at runtime (``State.list_suffixes``).
DEFAULT_LIST_SUFFIXES: tuple[str, ...] = (".toc", ".lof", ".lot", ".loalg", ".lol", ".tdo")
#: Files written by the tools on the canonical state (biber, makeindex for nomencl).
TOOL_SUFFIXES: tuple[str, ...] = (".bbl", ".nls")

#: List commands with a known derived file (other list commands: all list files).
LIST_COMMANDS: dict[str, str] = {
    "tableofcontents": ".toc",
    "minitoc": ".toc",
    "listoffigures": ".lof",
    "listoftables": ".lot",
    "listoftodos": ".tdo",
    "printbibliography": ".bbl",
    "bibliography": ".bbl",
    "printnomenclature": ".nls",
}


def derived_suffixes(list_suffixes: Sequence[str]) -> tuple[str, ...]:
    """Derived files of a document: its list files and the tool outputs (copied from the
    canonical state into every run)."""
    return (*list_suffixes, *TOOL_SUFFIXES)
