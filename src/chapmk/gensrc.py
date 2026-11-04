"""Generated TeX sources that keep the user's line numbers (PLAN §6.2).

All functions return text; writing files is the caller's job
(:func:`chapmk.files.write_if_changed`).
"""

from __future__ import annotations

from collections.abc import Sequence

from chapmk.analysis import Analysis

INI_PACKAGE = "chapmk-ini"
RUNTIME_PACKAGE = "chapmk"


def _ending(line: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n"


def format_source(analysis: Analysis) -> str:
    """Format source ``pre.tex``: ``\\RequirePackage{chapmk-ini}`` prepended to line 1,
    lines ``1..s-1`` verbatim, then the probes of state a format cannot keep (PDF objects,
    colour stacks, unrecorded catalog entries; checked by :func:`chapmk.fmt.ensure_format`,
    S13), the capture of the nodes left on the main vertical list (replayed by chapmk.sty)
    and ``\\endofdump`` (mylatexformat)."""
    nl = analysis.newline
    lines = list(analysis.lines[: analysis.split_line - 1])
    if not lines:
        lines = [nl]
    # \chapmk@formatbuild: chapmk-ini records what a format does not keep (S13)
    lines[0] = (
        "\\expandafter\\def\\csname chapmk@formatbuild\\endcsname{}"
        f"\\RequirePackage{{{INI_PACKAGE}}}{lines[0]}"
    )
    if not lines[-1].endswith("\n"):
        lines[-1] += nl
    check = (
        "\\ifdefined\\pdflastobj\\typeout{chapmk-pdf-objects:\\the\\pdflastobj,"
        "\\the\\pdflastxform,\\the\\pdflastximage}\\fi"
        # S13: the next free colour stack (1: none was created) and unrecorded \pdfcatalog ...
        "\\ifdefined\\pdfcolorstackinit\\typeout{chapmk-pdf-colorstacks:"
        "\\the\\numexpr\\pdfcolorstackinit direct{}\\relax}\\fi"
        "\\ifcsname chapmk@pdfunrecorded\\endcsname\\typeout{chapmk-pdf-unrecorded:"
        "\\csname chapmk@pdfunrecorded\\endcsname}\\fi"
        # S13: nodes left on the main vertical list go into a dumped box (chapmk-ini.sty)
        "\\ifdefined\\chapmk@capturemvl\\chapmk@capturemvl\\fi"
    )
    return "".join(lines) + check + "\\endofdump" + nl


def run_main(
    analysis: Analysis,
    selection: Sequence[str] | None,
    deny_names: Sequence[str] = (),
    list_suffixes: Sequence[str] = (),
) -> str:
    """Per-run main file for a run with the format.

    Lines ``1..s-1`` become empty lines (they are in the format). Line ``s-1`` gets
    ``\\csname endofdump\\endcsname``, the driver parameters for chapmk.sty (extra run-local
    register names ``deny_names``, config ``[state] ignore``; the list files ``list_suffixes`` that
    get unit markers), ``\\usepackage{chapmk}`` and, if
    ``selection`` is not ``None``, ``\\includeonly{...}`` (an empty selection gives a glue-only
    run). The rest is verbatim, so line numbers equal the user's main file.
    """
    s = analysis.split_line
    out = [_ending(line) for line in analysis.lines[: s - 1]]
    prefix = "\\csname endofdump\\endcsname"
    if deny_names:
        names = ",".join(deny_names)
        prefix += f"\\expandafter\\def\\csname chapmk@denynames\\endcsname{{{names}}}"
    if list_suffixes:
        exts = ",".join(s.lstrip(".") for s in list_suffixes)
        prefix += f"\\expandafter\\def\\csname chapmk@listexts\\endcsname{{{exts}}}"
    prefix += f"\\usepackage{{{RUNTIME_PACKAGE}}}"
    if selection is not None:
        prefix += "\\includeonly{" + ",".join(selection) + "}"
    # on its own line (s-1, empty here): the statement at line s may span several lines, and
    # the rest of the line of \endofdump is read in mylatexformat's special catcode state
    if not out:  # split at line 1: \documentclass not in the format (a fallback reason)
        raise ValueError("run_main needs a split point after line 1")
    out[-1] = prefix + out[-1]
    out.extend(analysis.lines[s - 1 :])
    return "".join(out)


def full_mode_input(analysis: Analysis) -> str:
    """TeX command-line input for full-mode and reference runs: the unmodified main file with
    ``chapmk-ini`` loaded before ``\\documentclass`` (externalize neutralisation, §6.4.1)."""
    return f"\\RequirePackage{{{INI_PACKAGE}}}\\input{{{analysis.main.name}}}"
