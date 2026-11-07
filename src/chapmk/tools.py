"""biber, BibTeX and makeindex (design §6.10): ``.bcf`` patch, nomenclature, and the one runner of
both tools for the full and the incremental builder (D6) with their errors (E7)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from chapmk.auxfile import segment_slices
from chapmk.errors import FallbackError, ToolError
from chapmk.proc import run
from chapmk.records import NLO_MARKER
from chapmk.texdist import TexDistribution
from chapmk.texsource import text_lines

#: makeindex style of nomencl
NOMENCL_STYLE = "nomencl.ist"
#: BibTeX's output in the output directory
BIBTEX_OUT = "bibtex.out"
_BLG_ERROR = re.compile(
    r"^(I couldn't open|I found no|Sorry---|Illegal, another \\bib|.*---line \d+ of file)"
)
#: at most this many error lines of a tool are shown
MAX_ERRORS = 5

_CITEKEY = re.compile(r'^(\s*)<bcf:citekey order="(\d+)"( intorder="\d+")?(.*)$')
_SECTION = re.compile(r'<bcf:section number="(\d+)">')


class ToolInputError(FallbackError):
    """The tool inputs cannot be assembled (e.g. several refsections with citations)."""


def _shown(lines: Sequence[str]) -> str:
    more = f"\n  ... ({len(lines) - MAX_ERRORS} more)" if len(lines) > MAX_ERRORS else ""
    return "".join(f"\n  {line}" for line in lines[:MAX_ERRORS]) + more


def biber_errors(blg: Path) -> list[str]:
    """The ``ERROR`` messages of a biber log (``.blg``), without the line prefixes."""
    if not blg.is_file():
        return []
    lines = text_lines(blg.read_text(encoding="utf-8", errors="replace"))
    return [line.split("> ERROR - ", 1)[1] for line in lines if "> ERROR - " in line]


def bibtex_errors(blg: Path) -> list[str]:
    """The error lines of a BibTeX log (``.blg``): missing files, data and style errors."""
    if not blg.is_file():
        return []
    lines = text_lines(blg.read_text(encoding="utf-8", errors="replace"))
    return [line.strip() for line in lines if _BLG_ERROR.match(line)]


def bibtex_inputs(outdir: Path) -> str | None:
    """Digest of what BibTeX reads from the aux files of ``outdir`` (``\\citation``,
    ``\\bibdata``, ``\\bibstyle`` lines); None if no aux file names a database
    (``\\bibdata``: BibTeX, or biblatex with ``backend=bibtex``)."""
    lines = sorted(
        (p.relative_to(outdir).as_posix(), line)
        for p in outdir.rglob("*.aux")
        for line in text_lines(p.read_text(encoding="utf-8", errors="surrogateescape"))
        if line.startswith(("\\citation{", "\\bibdata{", "\\bibstyle{"))
    )
    if not any(line.startswith("\\bibdata{") for _, line in lines):
        return None
    return hashlib.sha256(repr(lines).encode("utf-8", "surrogateescape")).hexdigest()


def run_bibtex(
    dist: TexDistribution, job: str, outdir: Path, inputs: Path, env: Mapping[str, str]
) -> None:
    """BibTeX on ``outdir/<job>.aux`` (``inputs``: the shadow tree with the ``.bib`` files); its
    output in :data:`BIBTEX_OUT`. Exit code 1 means warnings (as for latexmk, no failure);
    higher raises :class:`ToolError` with the error lines of the ``.blg`` (E7)."""
    out = outdir / BIBTEX_OUT
    r = run(dist.bibtex(job), cwd=outdir, env=dist.bibtex_env(env, inputs), log_path=out)
    if r.returncode > 1:
        blg = outdir / f"{job}.blg"
        found = bibtex_errors(blg) or [r.output.strip()[-500:]]
        raise ToolError(f"bibtex failed (see {blg}):{_shown(found)}", log=out)


def makeindex_errors(ilg: Path) -> list[str]:
    """The errors of a makeindex transcript (``.ilg``): each ``!!`` line with the next one."""
    if not ilg.is_file():
        return []
    lines = text_lines(ilg.read_text(encoding="utf-8", errors="replace"))
    return [
        f"{line.strip()} {lines[i + 1].strip() if i + 1 < len(lines) else ''}".strip()
        for i, line in enumerate(lines)
        if line.startswith("!!")
    ]


#: biber's output (stdout and stderr) in its output directory: ``--print-log`` prints it
BIBER_OUT = "biber.out"


def run_biber(
    dist: TexDistribution, job: str, outdir: Path, cwd: Path, env: Mapping[str, str]
) -> None:
    """biber on ``outdir/<job>.bcf`` (cwd: shadow tree, for the data sources); its output in
    :data:`BIBER_OUT`. A failure raises :class:`ToolError` with the ``ERROR`` lines of the
    ``.blg`` (E7) and the output file as ``log``."""
    out = outdir / BIBER_OUT
    r = run(dist.biber(job, outdir), cwd=cwd, env=env, log_path=out)
    if not r.ok:
        blg = outdir / f"{job}.blg"
        found = biber_errors(blg) or [r.output.strip()[-500:]]
        raise ToolError(f"biber failed (see {blg}):{_shown(found)}", log=out)


def run_makeindex(
    dist: TexDistribution,
    input_name: str,
    output_name: str,
    style: str | None,
    outdir: Path,
    env: Mapping[str, str],
    log_name: str = "makeindex.out",
) -> None:
    """makeindex in ``outdir`` (relative names). A failure raises :class:`ToolError` with the
    errors of the transcript (E7). Input errors makeindex reports with exit code 0 (e.g. for
    the segment markers of the canonical ``.nlo``) are not failures, as with latexmk."""
    r = run(
        dist.makeindex(input_name, output_name, style),
        cwd=outdir,
        env=env,
        log_path=outdir / log_name,
    )
    ilg = outdir / f"{Path(input_name).stem}.ilg"
    if not r.ok:
        found = makeindex_errors(ilg) or [r.output.strip()[-500:]]
        raise ToolError(f"makeindex failed on {input_name} (see {ilg}):{_shown(found)}")


def citekey_lines(bcf: str) -> list[str]:
    """``<bcf:citekey ...>`` lines of the ``.bcf`` in order (section 0 only, S5)."""
    lines: list[str] = []
    section = "0"
    for line in text_lines(bcf):
        m = _SECTION.search(line)
        if m:
            section = m.group(1)
        if _CITEKEY.match(line):
            if section != "0":
                raise ToolInputError("citations in a refsection other than 0 are not supported")
            lines.append(line)
    return lines


def citations_by_segment(main_aux_lines: list[str], bcf: str) -> dict[str, list[str]]:
    """Attribute a run's citekey elements to segments (S5): they correspond 1:1, in order, to
    the ``\\abx@aux@cite`` lines of the main aux, which the slices assign to segments."""
    elements = citekey_lines(bcf)
    out: dict[str, list[str]] = {}
    i = 0
    for seg, lines in segment_slices(main_aux_lines).items():
        n = sum(1 for line in lines if line.startswith("\\abx@aux@cite{"))
        out[seg] = elements[i : i + n]
        i += n
    if i != len(elements):
        raise ToolInputError(f".bcf has {len(elements)} citekeys, the aux {i} citations")
    return out


def patch_bcf(bcf: str, elements: Sequence[tuple[str, str]]) -> str:
    """The ``.bcf`` with its citekey list replaced by ``elements`` = (segment, element line) in
    document order. ``order`` is renumbered globally, one number per citation command: a new
    number whenever the segment or the original ``order`` changes (§6.10)."""
    renumbered: list[str] = []
    order, last = 0, ("", "")
    for seg, line in elements:
        m = _CITEKEY.match(line)
        if m is None:
            raise ToolInputError(f"not a citekey element: {line!r}")
        tag = (seg, m.group(2))
        if tag != last:
            order += 1
            last = tag
        renumbered.append(f'{m.group(1)}<bcf:citekey order="{order}"{m.group(3) or ""}{m.group(4)}')
    out: list[str] = []
    inserted = False
    for line in text_lines(bcf):
        if _CITEKEY.match(line):
            if not inserted:
                out += renumbered
                inserted = True
            continue
        if not inserted and line.strip() == "</bcf:section>" and renumbered:
            out += renumbered
            inserted = True
        out.append(line)
    return "\n".join(out) + "\n"


_DATALIST_NAME = re.compile(r'\bname="([^"]*)"')
_DATALIST_SECTION = re.compile(r'\bsection="([^"]*)"')


def datalists(bcf: str) -> dict[str, str]:
    """``<bcf:datalist>`` blocks of a ``.bcf`` by ``section/name``. biblatex declares a
    datalist where ``\\printbibliography`` (or a refcontext) is executed, so a run that
    excludes the bibliography's unit lacks it."""
    blocks: dict[str, str] = {}
    current: list[str] | None = None
    for line in text_lines(bcf):
        if current is None and line.lstrip().startswith("<bcf:datalist"):
            current = []
        if current is not None:
            current.append(line)
            if line.strip() == "</bcf:datalist>":
                text = "\n".join(current)
                name, section = _DATALIST_NAME.search(text), _DATALIST_SECTION.search(text)
                key = f"{section.group(1) if section else ''}/{name.group(1) if name else text}"
                blocks[key] = text
                current = None
    return blocks


def with_datalists(bcf: str, blocks: Mapping[str, str]) -> str:
    """The ``.bcf`` with its datalist blocks replaced by ``blocks`` (sorted by key, at the
    place of the first datalist, else before ``</bcf:controlfile>``)."""
    out: list[str] = []
    inside, placed = False, False
    lines = text_lines(bcf)
    for line in lines:
        if not inside and line.lstrip().startswith("<bcf:datalist"):
            inside = True
            if not placed:
                out += [blocks[k] for k in sorted(blocks)]
                placed = True
        if inside:
            inside = line.strip() != "</bcf:datalist>"
            continue
        if line.strip() == "</bcf:controlfile>" and not placed:
            out += [blocks[k] for k in sorted(blocks)]
            placed = True
        out.append(line)
    return "\n".join(out) + "\n"


def marked_file(segments: Sequence[str], entries: Mapping[str, list[str]]) -> str:
    """Canonical ``.nlo`` or ``.idx``: the entries of each segment in document order, with
    markers."""
    lines: list[str] = []
    for seg in segments:
        lines.append(f"{NLO_MARKER}{seg}")
        lines += entries.get(seg, [])
    return "\n".join(lines) + "\n"
