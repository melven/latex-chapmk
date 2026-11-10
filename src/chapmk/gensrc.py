"""Generated TeX sources that keep the user's line numbers (design §6.2).

All functions return text; writing files is the caller's job
(:func:`chapmk.files.write_if_changed`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from chapmk.analysis import Analysis

INI_PACKAGE = "chapmk-ini"
RUNTIME_PACKAGE = "chapmk"


@dataclass(frozen=True)
class FormatProbe:
    """State a format does not keep (§6.3.3, S13): ``tex`` (end of the format source) types
    ``chapmk-<name>:<value>`` into the log; ``reason`` maps the value to what the format part
    did, or None if the format keeps it. ``pattern`` replaces the probe line for a message of
    pdfTeX's own (group 1: the value)."""

    name: str
    tex: str
    reason: Callable[[str], str | None]
    pattern: str | None = None

    def find(self, log: str) -> str | None:
        """The reason this probe gives for a format build's log, None if none."""
        m = re.search(self.pattern or f"chapmk-{re.escape(self.name)}:(.*)", log)
        return self.reason(m.group(1).strip()) if m else None


def _typeout(name: str, test: str, value: str) -> str:
    return f"{test}\\typeout{{chapmk-{name}:{value}}}\\fi"


def _objects(value: str) -> str | None:
    _, forms, images = (int(v) for v in value.split(","))
    return f"creates PDF form xobjects or images ({forms}/{images})" if forms or images else None


def _written(value: str) -> str:
    name = value.strip('"').replace("\\jobname ", "\\jobname")
    return f"writes and closes a file ({name}, e.g. with filecontents)"


#: The probes, in the order their reasons are reported. Reserved ``\\pdfobj`` objects are
#: kept (only form xobjects and images count).
FORMAT_PROBES: tuple[FormatProbe, ...] = (
    FormatProbe(
        "pdf-objects",
        _typeout(
            "pdf-objects",
            "\\ifdefined\\pdflastobj",
            "\\the\\pdflastobj,\\the\\pdflastxform,\\the\\pdflastximage",
        ),
        _objects,
    ),
    FormatProbe(  # pdfTeX's warning at the dump
        "pdf-immediate",
        "",
        lambda _: "writes PDF objects immediately (e.g. the cmap package's ToUnicode maps)",
        pattern=r"dangling objects discarded()",
    ),
    FormatProbe(  # the next free colour stack: 1 if none was created
        "pdf-colorstacks",
        _typeout(
            "pdf-colorstacks",
            "\\ifdefined\\pdfcolorstackinit",
            "\\the\\numexpr\\pdfcolorstackinit direct{}\\relax",
        ),
        lambda v: (
            f"creates colour stacks ({int(v) - 1}, \\pdfcolorstackinit)" if int(v) > 1 else None
        ),
    ),
    FormatProbe(  # a \\pdfcatalog etc. without a braced argument (chapmk-ini.sty)
        "pdf-unrecorded",
        _typeout(
            "pdf-unrecorded",
            "\\ifcsname chapmk@pdfunrecorded\\endcsname",
            "\\csname chapmk@pdfunrecorded\\endcsname",
        ),
        lambda v: f"calls \\{v} without a braced argument",
    ),
    FormatProbe(  # a file the format part writes and closes, e.g. filecontents (chapmk-ini.sty)
        "file-written",
        _typeout(
            "file-written",
            "\\ifcsname chapmk@written\\endcsname",
            "\\csname chapmk@written\\endcsname",
        ),
        _written,
    ),
)


def lost_state(log: str) -> str | None:
    """What the format part did that a dump loses, from the log of the format build
    (:data:`FORMAT_PROBES`); None if nothing."""
    return next((r for p in FORMAT_PROBES if (r := p.find(log))), None)


def _ending(line: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n"


def format_source(analysis: Analysis) -> str:
    """Format source ``pre.tex``: ``\\RequirePackage{chapmk-ini}`` prepended to line 1,
    lines ``1..s-1`` verbatim, then the probes of state a format cannot keep (PDF objects,
    colour stacks, unrecorded catalog entries; checked by :func:`chapmk.fmt.ensure_format`,
    S13), the capture of the nodes left on the main vertical list (replayed by chapmk.sty),
    mylatexformat's font preloading switched off and ``\\endofdump`` (mylatexformat)."""
    nl = analysis.newline
    lines = list(analysis.lines[: analysis.split_line - 1])
    if not lines:
        lines = [nl]
    # \chapmk@formatbuild: chapmk-ini records what a format does not keep (S13);
    # \catcode64=12: mylatexformat reads the preamble after its own \makeatletter, a plain
    # build with @ "other" (sweep: theo543)
    lines[0] = (
        "\\catcode64=12 \\expandafter\\def\\csname chapmk@formatbuild\\endcsname{}"
        f"\\RequirePackage{{{INI_PACKAGE}}}{lines[0]}"
    )
    if not lines[-1].endswith("\n"):
        lines[-1] += nl
    check = "".join(p.tex for p in FORMAT_PROBES) + (
        # S13: nodes left on the main vertical list go into a dumped box (chapmk-ini.sty);
        # \csname: the preamble may leave @ "other", and \chapmk@capturemvl would be \chapmk
        # followed by text
        "\\ifcsname chapmk@capturemvl\\endcsname\\csname chapmk@capturemvl\\endcsname\\fi"
        # the catcode of @ the preamble leaves (an unclosed \makeatletter): \endofdump does
        # \makeatother before the dump; run_main sets it again (sweep: theo543)
        "\\expandafter\\xdef\\csname chapmk@atcatcode\\endcsname{\\the\\catcode64}"
        # sweep B2: mylatexformat typesets text and math in all sizes at \endofdump, which
        # sets up the math sizes and loads the fonts before the \begin{document} hooks that
        # redeclare fonts (mathptmx, mathpazo: the AMS symbol fonts); a plain build sets
        # them up at first use
        "\\expandafter\\let\\csname MYLATEX@fontpreloading\\endcsname\\relax"
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
    get unit markers), ``\\usepackage{chapmk}``, the catcode of ``@`` the preamble's format part
    left (stored by :func:`format_source`) and, if
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
    prefix += "\\catcode64=\\csname chapmk@atcatcode\\endcsname\\relax"
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
