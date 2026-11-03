"""biber and makeindex on the canonical state (PLAN §6.10): ``.bcf`` patch, nomenclature."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from chapmk.aux import segment_slices
from chapmk.errors import FallbackError
from chapmk.records import NLO_MARKER
from chapmk.texsource import text_lines

_CITEKEY = re.compile(r'^(\s*)<bcf:citekey order="(\d+)"( intorder="\d+")?(.*)$')
_SECTION = re.compile(r'<bcf:section number="(\d+)">')


class ToolInputError(FallbackError):
    """The tool inputs cannot be assembled (e.g. several refsections with citations)."""


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


def nomenclature_file(segments: Sequence[str], entries: Mapping[str, list[str]]) -> str:
    """Canonical ``.nlo``: the entries of each segment in document order, with markers."""
    lines: list[str] = []
    for seg in segments:
        lines.append(f"{NLO_MARKER}{seg}")
        lines += entries.get(seg, [])
    return "\n".join(lines) + "\n"
