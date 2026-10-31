"""The canonical build files in ``<build>/canon`` (PLAN §6.6, §6.7, §6.10): read views for
the dependency model, and the commit of a run (aux files, main aux, list files, ``.bcf`` patch
plus biber, ``.nlo`` plus makeindex)."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fastinc.analysis import Analysis
from fastinc.aux import (
    AGGREGATE,
    BACKREF,
    EQP,
    GLOBAL,
    LISTDATA,
    SELF,
    canonical_main_aux,
    classify,
    read_lines,
    segment_of_statements,
    statement_key,
    statements,
)
from fastinc.deps import cite_values, label_values
from fastinc.errors import ToolError
from fastinc.fullbuild import NOMENCL_STYLE
from fastinc.layout import Layout
from fastinc.proc import run
from fastinc.records import RunRecords, read_nomenclature
from fastinc.runner import DERIVED_SUFFIXES
from fastinc.state import SegmentArtifact, State
from fastinc.texdist import TexDistribution
from fastinc.tools import citations_by_segment, nomenclature_file, patch_bcf

#: list files written by every run (glue typesets them); .bbl and .nls come from the tools
LIST_SUFFIXES = tuple(s for s in DERIVED_SUFFIXES if s not in (".bbl", ".nls"))


def segments(analysis: Analysis) -> list[str]:
    """Segment ids in document order: G0, U1, G1, ..., Un, Gn."""
    return ["G0"] + [s for k in range(1, len(analysis.includes) + 1) for s in (f"U{k}", f"G{k}")]


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


@dataclass
class CanonView:
    """The canonical aux data at one point in time, for dirty checks."""

    main: list[str]  # statements of the canonical main aux
    unit_aux: dict[str, list[str]]  # unit segment -> statements of its aux file
    values: dict[str, str]  # imported-key values (deps)
    lists: str  # hash of the derived files (.toc ... .bbl .nls)

    def unit_self(self, seg: str) -> list[str]:
        """Self data of a unit (§6.8.1 item 6): self statements of its aux and of its
        main-aux slice."""
        own = [s for s in self.unit_aux.get(seg, []) if classify(s) == SELF]
        in_slice = [
            s
            for owner, s in zip(segment_of_statements(self.main), self.main, strict=True)
            if owner == seg and classify(s) == SELF
        ]
        return own + in_slice

    def glue_self(self) -> list[str]:
        return [
            s
            for owner, s in zip(segment_of_statements(self.main), self.main, strict=True)
            if (owner is None or owner.startswith("G")) and classify(s) == SELF
        ]

    def of_class(self, kind: str) -> list[str]:
        """Statements of one class in all canonical aux files (document order)."""
        out = [s for s in self.main if classify(s) == kind]
        for stmts in self.unit_aux.values():
            out += [s for s in stmts if classify(s) == kind]
        return out

    def eqp(self) -> dict[str, str]:
        return {statement_key(s): s for s in self.of_class(EQP)}

    def glue_data(self) -> list[str]:
        """Aux data read by the glue besides labels: list typesetting data, eqparbox,
        aggregates, backrefs (bibliography), unclassified statements and the glue's self data.
        Keyed and aggregate data are sorted: their position in the canonical main aux depends
        on which run wrote them."""
        keyed = [*self.of_class(LISTDATA), *self.of_class(EQP), *self.of_class(AGGREGATE)]
        return [
            *sorted(set(keyed)),
            *self.of_class(BACKREF),
            *self.of_class(GLOBAL),
            *self.glue_self(),
        ]


def read_canon(analysis: Analysis, canon: Path) -> CanonView:
    job = analysis.jobname
    main_path = canon / f"{job}.aux"
    main = statements(read_lines(main_path)) if main_path.is_file() else []
    unit_aux: dict[str, list[str]] = {}
    for k, inc in enumerate(analysis.includes, start=1):
        path = canon / inc.aux_name
        unit_aux[f"U{k}"] = statements(read_lines(path)) if path.is_file() else []
    values = label_values([main, *unit_aux.values()])
    values.update(cite_values(canon / f"{job}.bbl", main))
    h = hashlib.sha256()
    for suffix in DERIVED_SUFFIXES:
        h.update(f"{suffix}:{_digest(canon / f'{job}{suffix}')}\n".encode())
    return CanonView(main, unit_aux, values, h.hexdigest()[:16])


def commit_run(
    analysis: Analysis,
    layout: Layout,
    dist: TexDistribution,
    env: Mapping[str, str],
    state: State,
    run_name: str,
    recs: RunRecords,
    compiled: set[str],
) -> list[str]:
    """Commit run ``run_name`` (which compiled the unit segments ``compiled`` and all glue)
    into ``canon/`` and ``state``; returns the tool runs (biber, makeindex).

    Unit aux files, pages, citations, nomenclature entries and aggregates of the compiled
    units and of the glue come from the run; the canonical main aux keeps the unit content of
    the other units (§6.7.2). List files come from the run (TeX wrote them from all aux files
    it read, §6.7.1).
    """
    canon, job = layout.canon_dir, analysis.jobname
    run_dir = layout.runs_dir / run_name
    canon.mkdir(parents=True, exist_ok=True)
    order = segments(analysis)
    taken = [seg for seg in order if seg.startswith("G") or seg in compiled]
    for k, inc in enumerate(analysis.includes, start=1):
        if f"U{k}" in compiled:
            (canon / inc.aux_name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(run_dir / inc.aux_name, canon / inc.aux_name)
    for seg in taken:
        state.segments[seg] = SegmentArtifact(
            run_name, tuple(p.index for p in recs.pages if p.segment == seg)
        )
    run_main = statements(read_lines(run_dir / f"{job}.aux"))
    aggregates = list(dict.fromkeys(s for s in run_main if classify(s) == AGGREGATE))
    for seg in taken:
        state.aggregates[seg] = aggregates
    old_path = canon / f"{job}.aux"
    old_main = statements(read_lines(old_path)) if old_path.is_file() else []
    pages = sum(len(state.segments[s].pages) for s in order if s in state.segments)
    canonical = canonical_main_aux(
        run_main,
        old_main,
        {s for s in order if s.startswith("U") and s not in compiled},
        [a for s in order for a in state.aggregates.get(s, [])],
        pages,
    )
    _write_if_changed(old_path, "\n".join(canonical) + "\n")
    for suffix in LIST_SUFFIXES:
        src, dst = run_dir / f"{job}{suffix}", canon / f"{job}{suffix}"
        if src.is_file():
            shutil.copyfile(src, dst)
        else:
            dst.unlink(missing_ok=True)
    tools: list[str] = []
    if _commit_citations(analysis, layout, dist, env, state, run_dir, run_main, taken):
        tools.append("biber")
    if _commit_nomenclature(analysis, layout, dist, env, recs, taken):
        tools.append("makeindex")
    return tools


def _write_if_changed(path: Path, text: str) -> bool:
    data = text.encode("utf-8", "surrogateescape")
    if path.is_file() and path.read_bytes() == data:
        return False
    path.write_bytes(data)
    return True


def _commit_citations(
    analysis: Analysis,
    layout: Layout,
    dist: TexDistribution,
    env: Mapping[str, str],
    state: State,
    run_dir: Path,
    run_main: list[str],
    taken: list[str],
) -> bool:
    """Patch the run's ``.bcf`` with the canonical citations (S5) and run biber if the
    canonical ``.bcf`` changed or there is no ``.bbl`` yet."""
    job, canon = analysis.jobname, layout.canon_dir
    bcf = run_dir / f"{job}.bcf"
    if not bcf.is_file():
        return False
    text = bcf.read_text(encoding="utf-8", errors="surrogateescape")
    by_seg = citations_by_segment(run_main, text)
    for seg in taken:
        state.citations[seg] = by_seg.get(seg, [])
    elements = [(seg, e) for seg in segments(analysis) for e in state.citations.get(seg, [])]
    patched = patch_bcf(text, elements)
    changed = _write_if_changed(canon / f"{job}.bcf", patched)
    if not changed and (canon / f"{job}.bbl").is_file():
        return False
    r = run(dist.biber(job, canon), cwd=layout.shadow_dir, env=env, log_path=canon / "biber.out")
    if not r.ok:
        raise ToolError(f"biber failed, see {canon / f'{job}.blg'}")
    return True


def _commit_nomenclature(
    analysis: Analysis,
    layout: Layout,
    dist: TexDistribution,
    env: Mapping[str, str],
    recs: RunRecords,
    taken: list[str],
) -> bool:
    """Assemble the canonical ``.nlo`` per segment (§6.10) and run makeindex if it changed."""
    job, canon = analysis.jobname, layout.canon_dir
    nlo = canon / f"{job}.nlo"
    if not recs.nomenclature and not nlo.is_file():
        return False
    entries = read_nomenclature(nlo) if nlo.is_file() else {}
    for seg in taken:
        entries[seg] = recs.nomenclature.get(seg, [])
    changed = _write_if_changed(nlo, nomenclature_file(segments(analysis), entries))
    if not changed and (canon / f"{job}.nls").is_file():
        return False
    argv = dist.makeindex(nlo.name, f"{job}.nls", NOMENCL_STYLE)
    r = run(argv, cwd=canon, env=env, log_path=canon / "makeindex.out")
    if not r.ok:
        raise ToolError(f"makeindex failed: {r.output.strip()[-500:]}")
    return True
