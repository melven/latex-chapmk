"""Generated TeX sources that keep the user's line numbers (PLAN §6.2).

All functions return text; writing files is the caller's job (:func:`write_if_changed`).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from fastinc.analysis import Analysis, encode_source

INI_PACKAGE = "fastinc-ini"
RUNTIME_PACKAGE = "fastinc"


def _ending(line: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n"


def format_source(analysis: Analysis) -> str:
    """Format source ``pre.tex``: ``\\RequirePackage{fastinc-ini}`` prepended to line 1,
    lines ``1..s-1`` verbatim, then ``\\endofdump`` (mylatexformat)."""
    nl = analysis.newline
    lines = list(analysis.lines[: analysis.split_line - 1])
    if not lines:
        lines = [nl]
    lines[0] = f"\\RequirePackage{{{INI_PACKAGE}}}{lines[0]}"
    if not lines[-1].endswith("\n"):
        lines[-1] += nl
    return "".join(lines) + "\\endofdump" + nl


def run_main(
    analysis: Analysis, selection: Sequence[str] | None, deny_names: Sequence[str] = ()
) -> str:
    """Per-run main file for a run with the format.

    Lines ``1..s-1`` become empty lines (they are in the format). Line ``s`` is prefixed with
    ``\\csname endofdump\\endcsname``, the driver parameters for fastinc.sty (extra run-local
    register names ``deny_names``, config ``[state] ignore``), ``\\usepackage{fastinc}`` and, if
    ``selection`` is not ``None``, ``\\includeonly{...}`` (an empty selection gives a glue-only
    run). The rest is verbatim, so line numbers equal the user's main file.
    """
    s = analysis.split_line
    out = [_ending(line) for line in analysis.lines[: s - 1]]
    prefix = "\\csname endofdump\\endcsname"
    if deny_names:
        names = ",".join(deny_names)
        prefix += f"\\expandafter\\def\\csname fastinc@denynames\\endcsname{{{names}}}"
    prefix += f"\\usepackage{{{RUNTIME_PACKAGE}}}"
    if selection is not None:
        prefix += "\\includeonly{" + ",".join(selection) + "}"
    out.append(prefix + analysis.lines[s - 1])
    out.extend(analysis.lines[s:])
    return "".join(out)


def full_mode_input(analysis: Analysis) -> str:
    """TeX command-line input for full-mode and reference runs: the unmodified main file with
    ``fastinc-ini`` loaded before ``\\documentclass`` (externalize neutralisation, §6.4.1)."""
    return f"\\RequirePackage{{{INI_PACKAGE}}}\\input{{{analysis.main.name}}}"


def write_if_changed(path: Path, text: str) -> bool:
    """Write ``text`` (exact bytes, see :func:`fastinc.analysis.encode_source`) unless the file
    already has this content. Returns whether the file was written."""
    data = encode_source(text)
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True
