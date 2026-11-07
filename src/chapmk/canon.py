"""The canonical build files in ``<build>/canon`` (design §6.6, §6.7, §6.10): read views for
the dependency model, the commit of a run (aux files, main aux, list files, vectors,
citations, ``.nlo``) and the tools on the canonical state (``.bcf`` patch plus biber,
makeindex)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from chapmk.analysis import Analysis
from chapmk.auxfile import (
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
from chapmk.deps import cite_values, label_values, short_hash
from chapmk.errors import ChapmkError, SelfCheckError, ToolError
from chapmk.facts import DEFAULT_LIST_SUFFIXES, derived_suffixes
from chapmk.files import copy_atomic, digest, read_raw, write_atomic, write_if_changed
from chapmk.layout import Layout
from chapmk.predict import SegmentVectors, normalized
from chapmk.records import RunView, read_marked
from chapmk.segment import is_glue, is_unit, position, unit_id
from chapmk.state import SegmentArtifact, State, save_state
from chapmk.texdist import TexDistribution
from chapmk.texsource import split_lines
from chapmk.tools import (
    NOMENCL_STYLE,
    citations_by_segment,
    citekey_lines,
    datalists,
    marked_file,
    patch_bcf,
    run_biber,
    run_makeindex,
    with_datalists,
)

#: present in ``canon/`` while a batch commits (C7): from the first write of a canonical file
#: until the state is saved; a build that finds it starts cold
JOURNAL_FILE = ".in-progress"
_STOPPED = "stopped: "  # journal content after a chapmk error (fallback, tool) in the block


@contextmanager
def committing(canon: Path, state: State, runs: Sequence[str]) -> Iterator[None]:
    """The commit of a batch (C7, D2: the one place that persists the canonical state): the
    journal is written before the block changes ``canon/`` and ``state``; when the block
    ends normally, the state is saved and the journal removed. An exception (a tool error, a
    failed self-check, an interrupt) leaves the journal: the next build starts cold. A chapmk
    error is noted in it (``journal_reason``)."""
    canon.mkdir(parents=True, exist_ok=True)
    write_atomic(canon / JOURNAL_FILE, " ".join(runs))
    try:
        yield
    except ChapmkError as err:
        write_atomic(canon / JOURNAL_FILE, _STOPPED + str(err).split("\n", 1)[0][:200])
        raise
    save_state(state, canon)
    (canon / JOURNAL_FILE).unlink()


def journal_reason(canon: Path) -> str | None:
    """Why the canonical state is incomplete (a journal left by ``committing``), or None."""
    try:
        text = read_raw(canon / JOURNAL_FILE)
    except FileNotFoundError:
        return None
    if text.startswith(_STOPPED):
        return f"the previous build stopped while committing ({text[len(_STOPPED) :]})"
    return "the previous build was interrupted while committing"


def _digest(path: Path) -> str | None:
    return digest(path) if path.is_file() else None


@dataclass
class CanonView:
    """The canonical aux data at one point in time, for dirty checks."""

    main: list[str]  # statements of the canonical main aux
    unit_aux: dict[str, list[str]]  # unit segment -> statements of its aux file
    values: dict[str, str]  # imported-key values (deps)
    lists: str  # hash of the derived files (.toc ... .bbl .nls)
    list_digests: dict[str, str | None] = field(default_factory=dict)  # per suffix

    def lists_key(self, suffixes: Iterable[str] | None) -> str:
        """What a list reader depends on: ``.bbl,.toc=<hash>`` of the given derived files;
        all of them (``None``): :attr:`lists`."""
        if suffixes is None:
            return self.lists
        names = sorted(suffixes)
        digest = short_hash("".join(f"{s}:{self.list_digests.get(s) or ''}" for s in names))
        return f"{','.join(names)}={digest}"

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
            if (owner is None or is_glue(owner)) and classify(s) == SELF
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


def read_canon(
    analysis: Analysis, canon: Path, list_suffixes: Sequence[str] = DEFAULT_LIST_SUFFIXES
) -> CanonView:
    job = analysis.jobname
    main_path = canon / f"{job}.aux"
    main = statements(read_lines(main_path)) if main_path.is_file() else []
    unit_aux: dict[str, list[str]] = {}
    for k, inc in enumerate(analysis.includes, start=1):
        path = canon / inc.aux_name
        unit_aux[unit_id(k)] = statements(read_lines(path)) if path.is_file() else []
    values = label_values([main, *unit_aux.values()])
    values.update(cite_values(canon / f"{job}.bbl", main))
    h = hashlib.sha256()
    digests = {}
    for suffix in derived_suffixes(list_suffixes):
        digests[suffix] = _digest(canon / f"{job}{suffix}")
        h.update(f"{suffix}:{digests[suffix]}\n".encode())
    return CanonView(main, unit_aux, values, h.hexdigest()[:16], digests)


def commit_run(
    analysis: Analysis,
    layout: Layout,
    state: State,
    run: RunView,
    compiled: set[str],
) -> None:
    """Commit ``run`` (which compiled the unit segments ``compiled`` and all glue)
    into ``canon/`` and ``state``. Runs of a parallel batch are committed in document order;
    :func:`run_tools` follows once.

    Unit aux files, pages, vectors, citations, nomenclature entries and aggregates of the
    compiled units and of the glue come from the run; the canonical main aux keeps the unit
    content of the other units (§6.7.2). List files are committed by :func:`commit_lists`.
    """
    canon, job = layout.canon_dir, analysis.jobname
    run_name, run_dir, recs = run.name, run.directory, run.records
    canon.mkdir(parents=True, exist_ok=True)
    order = analysis.segments
    taken = [seg for seg in order if is_glue(seg) or seg in compiled]
    for k, inc in enumerate(analysis.includes, start=1):
        if unit_id(k) in compiled:
            (canon / inc.aux_name).parent.mkdir(parents=True, exist_ok=True)
            copy_atomic(run_dir / inc.aux_name, canon / inc.aux_name)
    for seg in taken:
        state.segments[seg] = SegmentArtifact(
            run_name, tuple(p.index for p in recs.pages if p.segment == seg)
        )
        if seg in recs.entries:
            exit_ = (
                recs.checkpoints.get(seg, {})
                if is_unit(seg)
                else {**recs.base, **recs.glue_exits.get(seg, {})}
            )
            state.vectors[seg] = SegmentVectors(
                normalized(recs.entry_state(seg)),
                normalized(exit_),
                frozenset(recs.absolute.get(seg, ())),
            )
    if recs.eqp_uses:  # Q records
        for seg in taken:
            state.eqp_tags[seg] = sorted(recs.eqp_uses.get(seg, ()))
    run_main = run.main_statements
    aggregates = list(dict.fromkeys(s for s in run_main if classify(s) == AGGREGATE))
    for seg in taken:
        state.aggregates[seg] = aggregates
    old_path = canon / f"{job}.aux"
    old_main = statements(read_lines(old_path)) if old_path.is_file() else []
    pages = sum(len(state.segments[s].pages) for s in order if s in state.segments)
    canonical = canonical_main_aux(
        run_main,
        old_main,
        {s for s in order if is_unit(s) and s not in compiled},
        [a for s in order for a in state.aggregates.get(s, [])],
        pages,
    )
    write_if_changed(old_path, "\n".join(canonical) + "\n")
    if run.bcf is not None:
        by_seg = citations_by_segment(run_main, run.bcf)
        for seg in taken:
            state.citations[seg] = by_seg.get(seg, [])
    for suffix, found in ((".nlo", recs.nomenclature), (".idx", recs.index)):
        path = canon / f"{job}{suffix}"
        if found or path.is_file():
            entries = read_marked(path) if path.is_file() else {}
            for seg in taken:
                entries[seg] = found.get(seg, [])
            if write_if_changed(path, marked_file(order, entries)):
                (canon / f"{suffix}{_CHANGED}").touch()


#: suffix of the flag files: the canonical .nlo/.idx changed since makeindex last ran on it
_CHANGED = "-changed"


_LMARK = re.compile(r"^\\chapmk@lmark\s*\{(/?)([UG]\d+)\}\s*$")


def unit_sections(text: str) -> dict[str, list[str]]:
    """Lines between the ``\\chapmk@lmark{U<k>}`` and ``{/U<k>}`` markers of a list file
    (the contributions of unit ``U<k>``, written while its aux file was read)."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in split_lines(text):
        m = _LMARK.match(line)
        if m:
            current = m.group(2) if not m.group(1) and is_unit(m.group(2)) else None
            if current is not None:
                out[current] = []
            continue
        if current is not None:
            out[current].append(line)
    return out


def splice_list(base: str, sections: Mapping[str, list[str]]) -> str | None:
    """``base`` with the unit sections replaced by ``sections``; None if a unit of
    ``sections`` has no complete marker pair in ``base``."""
    out: list[str] = []
    skipping: str | None = None
    done: set[str] = set()
    for line in split_lines(base):
        m = _LMARK.match(line)
        if skipping is not None:
            if m and m.group(1) == "/" and m.group(2) == skipping:
                out.append(line)
                done.add(skipping)
                skipping = None
            continue
        out.append(line)
        if m and not m.group(1) and m.group(2) in sections:
            skipping = m.group(2)
            out += sections[skipping]
    if skipping is not None or done != set(sections):
        return None
    return "".join(out)


def _check_kept_sections(new: str, old: str, kept: set[str], name: str) -> None:
    new_sections, old_sections = unit_sections(new), unit_sections(old)
    for seg in sorted(kept, key=position):
        if seg in new_sections and seg in old_sections and new_sections[seg] != old_sections[seg]:
            raise SelfCheckError(f"{name}: the entries of {seg} changed without a run of it")


def commit_lists(
    analysis: Analysis,
    layout: Layout,
    state: State,
    batch: Sequence[RunView],
) -> bool:
    """Canonical list files: the last run's, with the section of each unit committed by
    another run of the ``batch`` from that run (a parallel batch: no run read
    all new contributions). The sections of the other units are right in the last run: it
    wrote them from their canonical aux. Returns False if markers are missing (the list
    files then come from the last run unchanged).

    Self-check (C14): the section of a unit that no run of the batch compiled, as the last
    run wrote it from the unit's canonical aux, must equal its section in the previous
    canonical list file."""
    canon, job = layout.canon_dir, analysis.jobname
    last = batch[-1]
    names = {run.name: run for run in batch}
    complete = True
    for suffix in state.list_suffixes:
        src, dst = last.file(suffix), canon / f"{job}{suffix}"
        if not src.is_file():
            dst.unlink(missing_ok=True)
            continue
        base = read_raw(src)
        if dst.is_file():
            _check_kept_sections(
                base,
                read_raw(dst),
                set(analysis.unit_segments)
                - {seg for seg, art in state.segments.items() if art.run in names},
                dst.name,
            )
        sections: dict[str, list[str]] = {}
        for seg in analysis.unit_segments:
            run = state.segments[seg].run
            if run == last.name or run not in names:
                continue
            other = names[run].file(suffix)
            found = unit_sections(read_raw(other)) if other.is_file() else {}
            if seg in found:
                sections[seg] = found[seg]
            else:
                complete = False
        spliced = splice_list(base, sections)
        if spliced is None:
            complete, spliced = False, base
        write_if_changed(dst, spliced)
    return complete


_ORDER = re.compile(r' order="(\d+)"')


def _ranked_orders(lines: list[str]) -> list[str]:
    """Citekey lines with the ``order`` numbers replaced by their ranks: biber uses only
    their relative order; TeX's numbering may start later (citation commands that wrote no
    citekey), the patch numbers from 1."""
    found = sorted({int(m.group(1)) for line in lines if (m := _ORDER.search(line))})
    rank = {n: i + 1 for i, n in enumerate(found)}
    return [_ORDER.sub(lambda m: f' order="{rank[int(m.group(1))]}"', line) for line in lines]


def _check_bcf(patched: str, written: Path) -> None:
    if not written.is_file():
        return
    tex = read_raw(written)
    if _ranked_orders(citekey_lines(patched)) != _ranked_orders(citekey_lines(tex)):
        raise SelfCheckError(f"the patched .bcf citations differ from {written}")
    if datalists(patched) != datalists(tex):
        raise SelfCheckError(f"the patched .bcf datalists differ from {written}")


def run_tools(
    analysis: Analysis,
    layout: Layout,
    dist: TexDistribution,
    env: Mapping[str, str],
    state: State,
    batch: Sequence[RunView],
    full_run: RunView | None = None,
) -> list[str]:
    """biber on the patched ``.bcf`` (S5: the last run's ``.bcf`` with the canonical
    citations of all segments) if it changed or there is no ``.bbl``; makeindex if the
    canonical ``.nlo`` changed or there is no ``.nls``, and on the canonical ``.idx`` (default
    style, like latexmk) for ``.ind``. Returns the tool runs.

    Datalists are declared where ``\\printbibliography`` runs: the ``.bcf`` gets those of
    all runs of the ``batch`` and, unless a run of the batch compiled all units, those
    of the previous canonical ``.bcf`` (a unit with the bibliography may be excluded).

    Self-check (C14): if a run of the batch compiled all units (``full_run``), the patched
    citations and datalists must equal those TeX wrote into that run's ``.bcf``."""
    job, canon = analysis.jobname, layout.canon_dir
    tools: list[str] = []
    template = batch[-1].bcf
    if template is not None:
        elements = [(seg, e) for seg in analysis.segments for e in state.citations.get(seg, [])]
        patched = patch_bcf(template, elements)
        target = canon / f"{job}.bcf"
        blocks: dict[str, str] = {}
        if full_run is None and target.is_file():
            blocks.update(datalists(read_raw(target)))
        for run in batch:
            if run.bcf is not None:
                blocks.update(datalists(run.bcf))
        patched = with_datalists(patched, blocks)
        if full_run is not None:
            _check_bcf(patched, full_run.file(".bcf"))
        if write_if_changed(target, patched) or not (canon / f"{job}.bbl").is_file():
            try:
                run_biber(dist, job, canon, layout.shadow_dir, env)
            except ToolError:
                target.unlink()  # retried next time
                raise
            tools.append("biber")
    for src, out, style, name in (
        (".nlo", ".nls", NOMENCL_STYLE, "makeindex"),
        (".idx", ".ind", None, "makeindex (index)"),
    ):
        path, flag = canon / f"{job}{src}", canon / f"{src}{_CHANGED}"
        if path.is_file() and (flag.is_file() or not (canon / f"{job}{out}").is_file()):
            log = "makeindex.out" if src == ".nlo" else "makeindex-idx.out"
            run_makeindex(dist, path.name, f"{job}{out}", style, canon, env, log)
            flag.unlink(missing_ok=True)
            tools.append(name)
    return tools
