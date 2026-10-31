"""Parsing of the records written by fastinc.sty (PLAN §6.4.2, Appendix B)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from fastinc.analysis import Analysis
from fastinc.errors import FastincError

Vector = dict[int, int]

_REC = re.compile(r"^\\fastinc@(base|entry|gexit|abs|unit|ckpt|bkmlevels|counters)\{(.*)\}\s*$")
NLO_MARKER = "%fastinc-seg "


class RecordError(FastincError):
    """Records are missing or inconsistent (falls back to a full build)."""


def parse_vector(text: str) -> Vector:
    """``"12=3,0=-1,"`` → ``{12: 3, 0: -1}``."""
    vec: Vector = {}
    for item in text.split(","):
        if item.strip():
            n, _, v = item.partition("=")
            vec[int(n)] = int(v)
    return vec


_ALLOC = re.compile(r"^\\([^\s=]+)=\\count(\d+)\s*$", re.MULTILINE)


def register_names(logs: list[Path]) -> dict[int, str]:
    """``\\count`` register numbers → control sequence names, from the allocation lines
    (``\\c@figure=\\count284``) of the format and run logs (for messages)."""
    names: dict[int, str] = {}
    for log in logs:
        if log.is_file():
            for m in _ALLOC.finditer(log.read_text(errors="replace")):
                names.setdefault(int(m.group(2)), "\\" + m.group(1))
    return names


def parse_counters(text: str) -> dict[str, tuple[int, tuple[str, ...]]]:
    """``"chapter=279:section/figure/;page=0:;"`` → ``{"chapter": (279, ("section", "figure")),
    "page": (0, ())}``."""
    out: dict[str, tuple[int, tuple[str, ...]]] = {}
    for item in text.split(";"):
        name, sep, rest = item.partition("=")
        if not sep:
            continue
        reg, _, children = rest.partition(":")
        out[name.strip()] = (int(reg), tuple(c for c in children.split("/") if c))
    return out


def parse_indices(text: str) -> tuple[int, ...]:
    """``"3,5,"`` → ``(3, 5)``; unknown counters (``-1``) are dropped."""
    return tuple(i for i in (int(x) for x in text.split(",") if x.strip()) if i >= 0)


def _args(rest: str) -> tuple[str, str]:
    """Split ``a}{b`` (the text between the outer braces of a two-argument record)."""
    first, sep, second = rest.partition("}{")
    return (first, second) if sep else (rest, "")


@dataclass(frozen=True)
class PageRecord:
    """One shipped page: shipout index (0-based), segment, ``\\c@page`` and ``\\thepage``."""

    index: int
    segment: str
    value: int
    label: str


@dataclass
class RunRecords:
    """All records of one run."""

    base: Vector = field(default_factory=dict)
    entries: dict[str, Vector] = field(default_factory=dict)
    glue_exits: dict[str, Vector] = field(default_factory=dict)
    absolute: dict[str, tuple[int, ...]] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    checkpoints: dict[str, Vector] = field(default_factory=dict)
    bookmark_levels: dict[int, int] = field(default_factory=dict)
    pages: list[PageRecord] = field(default_factory=list)
    files: list[tuple[str, str]] = field(default_factory=list)
    nomenclature: dict[str, list[str]] = field(default_factory=dict)
    #: counter name -> (register index, names of the counters it resets)
    counters: dict[str, tuple[int, tuple[str, ...]]] = field(default_factory=dict)

    def reset_registers(self, counter: str) -> set[int]:
        """Registers of the counters reset, directly or transitively, when ``counter`` is
        stepped (``\\cl@<counter>`` closure; ``counter`` itself excluded)."""
        out: set[int] = set()
        todo, seen = list(self.counters.get(counter, (-1, ()))[1]), {counter}
        while todo:
            name = todo.pop()
            if name in seen or name not in self.counters:
                continue
            seen.add(name)
            reg, children = self.counters[name]
            if reg >= 0:
                out.add(reg)
            todo += children
        return out

    def segments_in_order(self) -> list[str]:
        """Segment ids in the order their entries were recorded."""
        return list(self.entries)

    def entry_state(self, segment: str) -> Vector:
        """Absolute entry vector of ``segment`` (baseline updated by the sparse entry)."""
        return {**self.base, **self.entries[segment]}


def _read_aux_records(path: Path, recs: RunRecords) -> None:
    for line in path.read_text(errors="replace").splitlines():
        m = _REC.match(line)
        if not m:
            continue
        kind, rest = m.groups()
        if kind == "base":
            recs.base = parse_vector(rest)
        elif kind == "bkmlevels":
            recs.bookmark_levels = parse_vector(rest)
        elif kind == "counters":
            recs.counters = parse_counters(rest)
        else:
            seg, arg = _args(rest)
            if kind == "entry":
                recs.entries[seg] = parse_vector(arg)
            elif kind == "gexit":
                recs.glue_exits[seg] = parse_vector(arg)
            elif kind == "abs":
                recs.absolute[seg] = parse_indices(arg)
            elif kind == "unit":
                recs.units[seg] = arg
            elif kind == "ckpt":
                recs.checkpoints[seg] = parse_vector(arg)


def _read_frec(path: Path, recs: RunRecords) -> None:
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("P "):
            index, seg, value, label = [*line[2:].split(" ", 3), ""][:4]
            recs.pages.append(PageRecord(int(index), seg, int(value), label))
        elif line.startswith("F "):
            seg, _, name = line[2:].partition(" ")
            recs.files.append((seg, name))


def read_nomenclature(path: Path) -> dict[str, list[str]]:
    """``.nlo`` entries per segment, split at the ``%fastinc-seg`` markers (§6.4.2 item 5)."""
    entries: dict[str, list[str]] = {}
    seg: str | None = None
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith(NLO_MARKER):
            seg = line[len(NLO_MARKER) :].strip()
            entries.setdefault(seg, [])
        elif seg is not None:
            entries[seg].append(line)
        elif line.strip():
            raise RecordError(f"{path}: nomenclature entry before the first segment marker")
    return entries


def read_run_records(run_dir: Path, analysis: Analysis) -> RunRecords:
    """Read the records of a finished run in ``run_dir``.

    Raises :class:`RecordError` if records are missing: no baseline, a page without segment,
    or a unit record that does not match the include order of the analysis.
    """
    job = analysis.jobname
    recs = RunRecords()
    main_aux = run_dir / f"{job}.aux"
    if not main_aux.is_file():
        raise RecordError(f"missing {main_aux}")
    _read_aux_records(main_aux, recs)
    for inc in analysis.includes:
        unit_aux = run_dir / inc.aux_name
        if unit_aux.is_file():
            _read_aux_records(unit_aux, recs)
    frec = run_dir / f"{job}.frec"
    if not frec.is_file():
        raise RecordError(f"missing {frec}")
    _read_frec(frec, recs)
    nlo = run_dir / f"{job}.nlo"
    if nlo.is_file():
        recs.nomenclature = read_nomenclature(nlo)
    if "G0" not in recs.entries:
        raise RecordError(f"{main_aux}: no baseline/entry records (fastinc.sty not loaded?)")
    for k, inc in enumerate(analysis.includes, start=1):
        name = recs.units.get(f"U{k}")
        if name is None:
            raise RecordError(f"{main_aux}: no record for include {k} ({inc.arg})")
        if name and _unit_name(name) != inc.arg:
            raise RecordError(f"{main_aux}: include {k} is {name!r}, expected {inc.arg!r}")
    return recs


def _unit_name(recorded: str) -> str:
    """Normalise a recorded unit name (``/ch1.tex``, ``chapters/ch1.tex``, ``ch1``)."""
    name = recorded.lstrip("/")
    if name.startswith("./"):
        name = name[2:]
    return name[:-4] if name.endswith(".tex") else name
