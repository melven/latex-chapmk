"""Parsing of the records written by chapmk.sty (PLAN §6.4.2, Appendix B)."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

from chapmk.analysis import Analysis
from chapmk.errors import FallbackError
from chapmk.files import read_log
from chapmk.texsource import text_lines

Vector = dict[int, int]

_REC = re.compile(
    r"^\\chapmk@(base|entry|gexit|abs|unit|ckpt|bkmlevels|counters|layout)\{(.*)\}\s*$"
)
NLO_MARKER = "%chapmk-seg "


class RecordError(FallbackError):
    """Records are missing, truncated or inconsistent (falls back to a full build)."""


def parse_vector(text: str) -> Vector:
    """``"12=3,0=-1,"`` → ``{12: 3, 0: -1}``."""
    vec: Vector = {}
    for item in text.split(","):
        if item.strip():
            n, _, v = item.partition("=")
            vec[int(n)] = int(v)
    return vec


_ALLOC = re.compile(r"^\\([^\s=]+)=\\count(\d+)\s*$", re.MULTILINE)


_LOG_PAREN = re.compile(r"\(([^\s()]*)|\)")
_LOG_FILE = re.compile(r"[^\s()]+\.(sty|cls|def|cfg|clo|ldf|fd|tex)$")


def register_names(logs: list[Path]) -> dict[int, str]:
    """``\\count`` register numbers → names for messages, with the package that allocated
    them (``\\c@instcount [biblatex]``): the allocation lines (``\\c@figure=\\count284``)
    of the format and run logs, attributed to the innermost file open in the log there."""
    names: dict[int, str] = {}
    for log in logs:
        if not log.is_file():
            continue
        stack: list[str | None] = []  # open files (None: other parentheses)
        for line in text_lines(read_log(log)):
            m = _ALLOC.match(line)
            if m:
                package = next((f for f in reversed(stack) if f), None)
                name = "\\" + m.group(1)
                names.setdefault(int(m.group(2)), f"{name} [{package}]" if package else name)
                continue
            for p in _LOG_PAREN.finditer(line):
                if p.group(0) == ")":
                    if stack:
                        stack.pop()
                else:
                    f = p.group(1)
                    stack.append(Path(f).stem if _LOG_FILE.match(f) else None)
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


def tex_phases(recs: RunRecords, total: float) -> dict[str, float]:
    """Breakdown of a run's TeX time (``total``: process wall time): ``format`` (start until
    chapmk.sty loads: format and preamble before the split), ``preamble`` (rest until the
    end of ``\\begin{document}``), ``glue``, ``units`` (compiled and excluded), ``end``
    (``\\end{document}`` to process exit: aux re-read, list files, PDF finalisation), and
    ``pictures``: time inside top-level pgf/TikZ pictures (part of glue and units)."""
    out = {"format": 0.0, "preamble": 0.0, "glue": 0.0, "units": 0.0, "end": 0.0, "pictures": 0.0}
    depth, start = 0, 0.0
    for name, t in recs.times:  # top-level pgf pictures (included in glue/units)
        if name == "picture+":
            depth += 1
            if depth == 1:
                start = t
        elif name == "picture-" and depth > 0:
            depth -= 1
            if depth == 0:
                out["pictures"] += t - start
    points = [(n, t) for n, t in recs.times if not n.startswith("picture")]
    if not points:
        return {k: round(v, 3) for k, v in out.items()}
    marks = dict(points)
    out["format"] = marks.get("load", 0.0)
    out["preamble"] = marks.get("begin", 0.0) - out["format"]
    for (name, t), (_, t_next) in itertools.pairwise(points):
        if name[:1] in "GU" and name[1:].isdigit():
            out["glue" if name[0] == "G" else "units"] += t_next - t
    out["end"] = max(0.0, total - marks.get("end", total))
    return {k: round(v, 3) for k, v in out.items()}


def glue_times(recs: RunRecords, minimum: float = 0.05) -> dict[str, float]:
    """TeX time per glue segment (at least ``minimum`` seconds): which part of the main file
    body (front matter, lists, bibliography, ...) costs time in every run."""
    points = [(n, t) for n, t in recs.times if not n.startswith("picture")]
    out = {}
    for (name, t), (_, t_next) in itertools.pairwise(points):
        if name[:1] == "G" and name[1:].isdigit() and t_next - t >= minimum:
            out[name] = round(t_next - t, 3)
    return out


def parse_vector_names(text: str) -> dict[str, int]:
    """``"twoside=1,openright=0"`` → ``{"twoside": 1, "openright": 0}``."""
    out: dict[str, int] = {}
    for item in text.split(","):
        name, sep, value = item.partition("=")
        if sep:
            out[name.strip()] = int(value)
    return out


def read_main_records(main_aux: Path) -> RunRecords:
    """The records of one main aux file (e.g. the canonical one)."""
    recs = RunRecords()
    if main_aux.is_file():
        _read_aux_records(main_aux, recs)
    return recs


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
    #: elapsed TeX time in seconds at points of the run (``load``, ``begin``, segment ids,
    #: ``end``; M6 breakdown), in order
    times: list[tuple[str, float]] = field(default_factory=list)
    #: eqparbox tags used per segment (``Q`` records; M6)
    eqp_uses: dict[str, set[str]] = field(default_factory=dict)
    #: page layout flags (``twoside``, ``openright``: 0/1)
    layout: dict[str, int] = field(default_factory=dict)
    #: per compiled unit: starts under twoside+openright (``O`` records)
    openright: dict[str, bool] = field(default_factory=dict)
    #: suffixes of the list files read by ``\\@starttoc`` (``L`` records)
    list_suffixes: set[str] = field(default_factory=set)
    #: pseudo registers of the kernel's mark classes (running heads) -> class name
    #: (``K <id> <class>``; values: digests of the last mark's text)
    mark_classes: dict[int, str] = field(default_factory=dict)
    #: ``\\marks`` registers outside the kernel's classes that hold marks (``\\mark`` is 0;
    #: ``K primitive <n>``): they cannot be restored for excluded units
    primitive_marks: set[int] = field(default_factory=set)

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

    def entry_state(self, segment: str) -> Vector:
        """Absolute entry vector of ``segment`` (baseline updated by the sparse entry)."""
        return {**self.base, **self.entries[segment]}


def _read_aux_records(path: Path, recs: RunRecords) -> None:
    for line in text_lines(read_log(path)):
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
        elif kind == "layout":
            recs.layout = parse_vector_names(rest)
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
    for line in text_lines(read_log(path)):
        if line.startswith("P "):
            index, seg, value, label = [*line[2:].split(" ", 3), ""][:4]
            recs.pages.append(PageRecord(int(index), seg, int(value), label))
        elif line.startswith("Q "):
            seg, _, tag = line[2:].partition(" ")
            recs.eqp_uses.setdefault(seg, set()).add(tag.strip())
        elif line.startswith("T "):
            _, point, value = line.split(" ", 2)
            recs.times.append((point, int(value) / 65536))
        elif line.startswith("F "):
            seg, _, name = line[2:].partition(" ")
            recs.files.append((seg, name))
        elif line.startswith("L "):
            recs.list_suffixes.add("." + line[2:].strip())
        elif line.startswith("O "):
            seg, _, flag = line[2:].partition(" ")
            recs.openright[seg] = flag.strip() == "1"
        elif line.startswith("K primitive "):
            recs.primitive_marks.add(int(line[12:]))
        elif line.startswith("K "):
            reg, _, name = line[2:].partition(" ")
            recs.mark_classes[int(reg)] = name.strip()


def read_nomenclature(path: Path) -> dict[str, list[str]]:
    """``.nlo`` entries per segment, split at the ``%chapmk-seg`` markers (§6.4.2 item 5)."""
    entries: dict[str, list[str]] = {}
    seg: str | None = None
    for line in text_lines(read_log(path)):
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
    try:
        return _read_run_records(run_dir, analysis)
    except (ValueError, IndexError) as err:  # truncated or malformed record lines
        raise RecordError(f"{run_dir}: unreadable records ({err})") from err


def _read_run_records(run_dir: Path, analysis: Analysis) -> RunRecords:
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
        raise RecordError(f"{main_aux}: no baseline/entry records (chapmk.sty not loaded?)")
    for k, inc in enumerate(analysis.includes, start=1):
        name = recs.units.get(f"U{k}")
        if name is None:
            raise RecordError(f"{main_aux}: no record for include {k} ({inc.arg})")
        if name and _unit_name(name) != inc.arg:
            raise RecordError(f"{main_aux}: include {k} is {name!r}, expected {inc.arg!r}")
    known = {"G0"} | {f"{p}{k}" for k in range(1, len(analysis.includes) + 1) for p in "UG"}
    for page in recs.pages:
        if page.segment not in known:
            raise RecordError(f"{frec}: page {page.index} has no known segment ({page.segment!r})")
    return recs


def _unit_name(recorded: str) -> str:
    """Normalise a recorded unit name (``/ch1.tex``, ``chapters/ch1.tex``, ``ch1``)."""
    name = recorded.lstrip("/")
    if name.startswith("./"):
        name = name[2:]
    return name[:-4] if name.endswith(".tex") else name
