"""Document facts shared by the analysis, the builder, the runs and the shadow tree (D4):
one table each, so the static and the runtime checks cannot disagree.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence

# Features that force full mode (design §1, §6.14). A new one is one entry in one of these
# tables; the preamble scan (analysis) and the run-time check (:func:`runtime_reason`) read
# them.

#: Package -> why it is not supported: checked in the preamble (analysis) and, as
#: ``<name>.sty``, in the ``.fls`` of the format build and of every run (also when a class or
#: another package loads them).
UNSUPPORTED_PACKAGES: dict[str, str] = {
    "glossaries": "writes its own glossary files",
    "glossaries-extra": "writes its own glossary files",
    "imakeidx": "runs makeindex itself through shell escape",
    "minted": "needs shell escape",
    "acronym": "keeps the first use of each acronym in macros, S17",
    "perpage": "resets counters per page through aux data",
    "hyperxmp": "writes its XMP packet with the run's page count and job name",
    "pdfx": "PDF/A: writes its XMP file and PDF objects in the preamble",
}

#: Package -> (package it needs for incremental builds, why); checked at run time.
REQUIRED_COMPANIONS: dict[str, tuple[str, str]] = {
    "hyperref": ("bookmark", "the outline comes from bookmark's records"),
}

#: Pattern in the comment-free sources (preamble scan) -> reason.
UNSUPPORTED_SOURCE: dict[str, str] = {
    r"\\makeglossaries\b": "\\makeglossaries is not supported",
    r"\\bibliography\s*\{": "BibTeX (\\bibliography) is not supported; use biblatex with biber",
}

#: Start of a main-aux line of a run -> reason (also when a class or package writes it).
UNSUPPORTED_AUX: dict[str, str] = {
    "\\bibdata{": (
        "BibTeX in use (\\bibdata in the aux file, e.g. biblatex with backend=bibtex); "
        "use biblatex with biber for incremental builds"
    ),
}


def package_reason(name: str, at_runtime: bool = False) -> str:
    """The fallback reason for the unsupported package ``name``."""
    where = "; loaded at runtime" if at_runtime else ""
    return f"package {name!r} is not supported ({UNSUPPORTED_PACKAGES[name]}{where})"


def source_reasons(text: str) -> list[str]:
    """Reasons of :data:`UNSUPPORTED_SOURCE` found in comment-free source text."""
    return [why for pattern, why in UNSUPPORTED_SOURCE.items() if re.search(pattern, text)]


def unsupported_loaded(loaded: Collection[str]) -> str | None:
    """The reason for the first unsupported package among the file names ``loaded``."""
    pkg = next((p for p in sorted(UNSUPPORTED_PACKAGES) if f"{p}.sty" in loaded), None)
    return package_reason(pkg, at_runtime=True) if pkg else None


def runtime_reason(loaded: Collection[str], main_aux: Sequence[str]) -> str | None:
    """The first fallback reason of a run or format build: ``loaded`` are the file names it
    read (``.fls``, e.g. ``hyperref.sty``), ``main_aux`` the lines of its main aux file."""
    if reason := unsupported_loaded(loaded):
        return reason
    for start, why in UNSUPPORTED_AUX.items():
        if any(line.startswith(start) for line in main_aux):
            return why
    for pkg, (companion, why) in REQUIRED_COMPANIONS.items():
        if f"{pkg}.sty" in loaded and f"{companion}.sty" not in loaded:
            return (
                f"{pkg} without the {companion} package ({why}; load {companion} to build "
                "incrementally)"
            )
    return None


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
#: Files written by the tools on the canonical state (biber, makeindex for nomencl and the
#: index).
TOOL_SUFFIXES: tuple[str, ...] = (".bbl", ".nls", ".ind")

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
    "printindex": ".ind",
}


def derived_suffixes(list_suffixes: Sequence[str]) -> tuple[str, ...]:
    """Derived files of a document: its list files and the tool outputs (copied from the
    canonical state into every run)."""
    return (*list_suffixes, *TOOL_SUFFIXES)
