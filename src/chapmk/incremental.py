"""Incremental builder (design §5, §6.9): full mode for fallback reasons, otherwise the
fixpoint loop.

Each iteration compiles the dirty compilation units (all units: a full run; none: a glue-only
run), each run with the glue, in a batch of up to ``-j`` parallel runs with predicted start
states (§6.9.3), commits the results into the canonical state (:mod:`chapmk.canon`) and
recomputes the dirty set from the dependency model (§6.8):

- a unit is dirty if its sources changed, an imported label or citation value changed, its
  self data was unstable, its observed entry state changed or it follows such a unit (tail
  run: without prediction the later units are compiled in the same run), unclassified
  or aggregate aux data changed, or a list file it typesets changed; *global* units (lint,
  §6.8.4) are compiled in every run, and with all later units when they are dirty;
- the glue (compiled in every run) is valid if its inputs (derived files, imported values,
  glue aux data, glue sources) equal those the committed glue run started from.

The loop ends when nothing is dirty and the glue is valid (then every committed segment was
compiled from the final canonical state); otherwise after :data:`MAX_ITERATIONS` batches the
build falls back to full mode. A cold build is the same loop starting with all units dirty
and an empty canonical state (§6.9.4).
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import chapmk
from chapmk.analysis import Analysis
from chapmk.auxfile import (
    command_name,
    read_lines,
    run_input_main_aux,
    statements,
)
from chapmk.canon import (
    CanonView,
    commit_lists,
    commit_run,
    committing,
    journal_reason,
    read_canon,
    run_tools,
)
from chapmk.config import Config
from chapmk.deps import imports
from chapmk.dirty import DirtyRules
from chapmk.errors import FallbackError, TexError
from chapmk.facts import UNIT_HEADINGS, derived_suffixes, runtime_reason, unsupported_loaded
from chapmk.files import changed_files, digest, source_name, write_atomic
from chapmk.fmt import (
    FORMAT_NAME,
    FormatInfo,
    ensure_format,
    format_dist_inputs,
    format_inputs,
    format_stamp,
)
from chapmk.fullbuild import full_build
from chapmk.layout import Layout
from chapmk.lint import glue_hints
from chapmk.logs import short_list
from chapmk.outputs import (
    failed_run,
    is_published,
    mark_published,
    publish_state,
)
from chapmk.pictures import (
    PICS_FILE,
    collect_garbage,
    driver_file,
    export_run,
    parse_pictures,
    picture_stamp,
    record_inputs,
    refresh_cache,
)
from chapmk.predict import (
    Vector,
    normalized,
    rewrite_checkpoint,
)
from chapmk.recorder import changed_signatures, dist_signatures, loaded_names, source_inputs
from chapmk.records import (
    RunRecords,
    RunView,
    glue_times,
    read_main_records,
    register_names,
    tex_phases,
)
from chapmk.runner import RunSpec, prepare_run_dir, run_batch
from chapmk.schedule import Schedule
from chapmk.segment import is_glue, is_unit, position, unit_id
from chapmk.shadow import sync_project_shadow
from chapmk.sources import UnitSources, anchor_owners, load_lint_cache, save_lint_cache
from chapmk.state import CorruptStateError, State, UnitInputs, load_state
from chapmk.texdist import TexDistribution
from chapmk.timing import Timings

MAX_ITERATIONS = 8
FULL_ONLY_FILE = "full-only.json"


@dataclass
class BuildReport:
    """What a build did (``chapmk build --report``): mode, reason, runs (with selection and
    dirty reasons), compiled includes, lint warnings."""

    mode: str  # "full", "cold", "incremental" or "noop"
    reason: str | None = None
    runs: list[dict[str, Any]] = field(default_factory=list)
    compiled: list[str] = field(default_factory=list)
    seconds: float = 0.0
    pdf: str | None = None
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)  # wall time per phase
    # advice that depends on measured times (slow glue), kept apart from the warnings
    hints: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1)


@dataclass
class Context:
    """Everything a build step needs."""

    analysis: Analysis
    layout: Layout
    dist: TexDistribution
    config: Config
    base_env: Mapping[str, str]
    say: Callable[[str], None]
    timings: Timings = field(default_factory=Timings)

    @property
    def job(self) -> str:
        return self.analysis.jobname

    def env(self, epoch: int) -> dict[str, str]:
        return self.dist.environment(epoch, self.base_env, self.layout.fmt_dir)


# --- file attribution ------------------------------------------------------------------------


def _source_file(ctx: Context, recorded: str) -> str | None:
    """Source-tree path (relative, posix) of a file name recorded by a run, if it is one."""
    name = source_name(recorded, ctx.analysis.source_dir)
    return name if name is not None and (ctx.layout.shadow_dir / name).is_file() else None


def _hashes(ctx: Context, names: set[str]) -> dict[str, str]:
    return {n: digest(ctx.analysis.source_dir / n) for n in sorted(names)}


def _segment_files(ctx: Context, recs: RunRecords) -> dict[str, dict[str, str]]:
    files: dict[str, set[str]] = {}
    for seg, recorded in recs.files:
        name = _source_file(ctx, recorded)
        if name is not None:
            files.setdefault(seg, set()).add(name)
    return {seg: _hashes(ctx, names) for seg, names in files.items()}


def _global_files(ctx: Context, run: RunView, attributed: set[str]) -> dict[str, str]:
    """Source files read by the run but attributed to no segment, plus biblatex data sources."""
    names = source_inputs(run.file(".fls"), ctx.layout.shadow_dir, ctx.analysis.source_dir)
    names -= attributed
    if run.bcf is not None:
        for m in re.finditer(r"<bcf:datasource[^>]*>([^<]+)</bcf:datasource>", run.bcf):
            if (ctx.analysis.source_dir / m.group(1)).is_file():
                names.add(Path(m.group(1)).as_posix())
    return _hashes(ctx, names - attributed)


def _anchor_warning(a: Analysis, owner: str, reader: str, command: str, line: int) -> str:
    """The warning for a command that used the anchor of ``owner`` (S19), with the fix."""
    where = f"{a.main.name if is_glue(reader) else a.include_of(reader).name + '.tex'}:{line}"
    arg = a.include_of(owner).arg
    if command == "addcontentsline":
        return (
            f"{where}: \\addcontentsline has no anchor of its own: its ToC entry and bookmark "
            f"link to the last anchor in {arg}, also in a plain build (with hyperref, KOMA's "
            f"\\chapter* and listof=totoc set none); {arg} is compiled in every run. Put "
            "\\phantomsection before it (before a new page: \\cleardoublepage\\phantomsection)"
        )
    return (
        f"{where}: \\{command} takes its number and target from the last numbered item in "
        f"{arg} (none before it in its own part), also in a plain build; {arg} is compiled "
        "in every run. Put it after the item it refers to"
    )


def _check_runtime_support(run: RunView, fmt: FormatInfo) -> None:
    """Packages loaded by the format or the run (also those loaded by the class)."""
    loaded = run.loaded | loaded_names(fmt.directory / f"{fmt.name}.fls")
    reason = runtime_reason(loaded, run.main_lines)
    if reason:
        raise FallbackError(reason, True)


def _write(path: Path, stmts: list[str]) -> None:
    write_atomic(path, "\n".join(stmts) + "\n")


# --- the fixpoint loop -------------------------------------------------------------------------


class Fixpoint:
    """Dirty sets, batches of runs and commits of one build (§6.9.2)."""

    def __init__(self, ctx: Context, state: State, fmt: FormatInfo) -> None:
        self.ctx, self.state, self.fmt = ctx, state, fmt
        self.a = ctx.analysis
        self.units = self.a.unit_segments
        self.warnings: list[str] = []
        self.sources = UnitSources(self.a, state, ctx.config, load_lint_cache(ctx.layout.canon_dir))
        self.rules = DirtyRules(self.a, state, self.sources.scan, self._warn)
        self.schedule = Schedule(
            self.a, state, self.sources.is_global, ctx.config.effective_jobs, ctx.say
        )
        # one dict for the messages of both (filled from the logs after the first batch)
        self.register_names = self.rules.register_names = self.schedule.register_names
        self._view: CanonView | None = None  # canonical view after the last batch (unchanged since)
        self.views: dict[str, RunView] = {}  # runs of this build, parsed once (D5)

    def _warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)
            self.ctx.say(f"warning: {msg}")

    def pictures_file(self, view: CanonView) -> str:
        """Driver parameters of the picture cache (§6.17) for runs from ``view``: directory and
        stamp (format, main file). Figures whose code references a label or citation that
        changed since their export are removed first (the picture is exported again)."""
        ctx = self.ctx
        if not ctx.config.picture_cache:
            return driver_file(None, ctx.layout.shadow_dir, "", {})
        fig = ctx.layout.fig_dir
        refresh_cache(fig, view.values, self.a.source_dir)
        stamp = picture_stamp(self.state.format_stamp, self.state.fingerprints)
        return driver_file(fig, ctx.layout.shadow_dir, stamp, {})

    def batch(
        self,
        groups: list[list[int] | None],
        dirty: Mapping[str, list[str]],
        glue: str | None,
        number: int,
    ) -> list[dict[str, Any]]:
        """Compile the groups (each plus glue) in parallel runs, verify the predictions,
        commit in document order and recompute the dirty set."""
        ctx, a, state = self.ctx, self.a, self.state
        canon = ctx.layout.canon_dir
        parallel = len(groups) > 1
        pred: dict[str, tuple[Vector, Vector]] = {}
        rewrites: dict[int, dict[str, tuple[Vector, frozenset[int]]]] = {}
        if parallel:
            layout = self._canon_records(canon).layout
            pred, rewrites = self.schedule.predictions([g for g in groups if g is not None], layout)
            self.schedule.state_before = dict(
                state.vectors
            )  # verification uses the vectors predicted from
        t = ctx.timings
        t.lap("plan")  # dirty-set planning, groups, predictions
        registers = {n: reg for n, (reg, _) in self._canon_records(canon).counters.items()}
        pre = self._view if self._view is not None else read_canon(a, canon, state.list_suffixes)
        pre_glue = self.rules.glue_inputs(pre)
        t.lap("canon")
        pictures_text = self.pictures_file(pre)
        t.lap("pictures")
        specs: list[RunSpec] = []
        compiled_by_run: list[set[str]] = []
        for j, group in enumerate(groups):
            name = state.new_run_name()
            ks = list(range(1, len(self.units) + 1)) if group is None else group
            args = None if group is None else tuple(a.includes[k - 1].arg for k in ks)
            compiled = {unit_id(k) for k in ks}
            for seg in sorted(compiled, key=position):
                for hit in self.sources.lint(seg):
                    self._warn(hit.message())
            what = "all units" if args is None else ", ".join(args) if args else "glue only"
            ctx.say(f"run {name}: {what}")
            spec = RunSpec(name, args)
            run_dir = prepare_run_dir(
                a,
                ctx.layout,
                spec,
                canon_dir=canon if canon.is_dir() else None,
                deny_names=ctx.config.state_ignore,
                list_suffixes=state.list_suffixes,
            )
            main_aux = run_dir / f"{ctx.job}.aux"
            if main_aux.is_file():
                excluded = {seg for seg in self.units if seg not in compiled}
                stmts = run_input_main_aux(statements(read_lines(main_aux)), excluded)
                _write(main_aux, stmts)
            for seg, (exit_, keep) in rewrites.get(j, {}).items():
                path = run_dir / a.include_of(seg).aux_name
                stmts = rewrite_checkpoint(statements(read_lines(path)), exit_, registers, keep)
                _write(path, stmts)
            (run_dir / PICS_FILE).write_text(pictures_text, encoding="utf-8")
            specs.append(spec)
            compiled_by_run.append(compiled)
        all_compiled = set().union(*compiled_by_run)
        pre_self = {seg: pre.unit_self(seg) for seg in all_compiled}
        env = ctx.env(state.epoch)
        t.lap("prepare")  # run directories
        results = run_batch(a, ctx.layout, ctx.dist, env, specs, self.fmt.path, len(specs))
        t.lap("tex")
        for r in results:
            if not r.ok:
                err = TexError("pdflatex failed", first_error=r.first_error)
                raise failed_run(a, ctx.layout, r.directory, err)
        views = [RunView(r.directory, a) for r in results]
        self.views.update((v.name, v) for v in views)
        for view in views:  # before the records: an unsupported package can break them
            _check_runtime_support(view, self.fmt)
        all_recs = [v.records for v in views]
        for recs in all_recs:  # list files with other extensions: stored and spliced from now on
            for suffix in sorted(recs.list_suffixes - set(state.list_suffixes)):
                state.list_suffixes.append(suffix)
        for recs in all_recs:
            if recs.primitive_marks:
                regs = ", ".join(f"\\marks{n}" for n in sorted(recs.primitive_marks))
                raise FallbackError(
                    f"running heads use primitive marks ({regs}; e.g. \\mark in a package): "
                    "excluded units cannot restore them, so every build is a full build "
                    "(supported: the kernel's mark classes, \\markboth, \\markright, \\InsertMark)",
                    True,
                )
        if not self.register_names:
            self.register_names.update(
                register_names([self.fmt.directory / f"{self.fmt.name}.log", results[0].log])
            )
            for reg, name in all_recs[0].mark_classes.items():
                self.register_names[reg] = f"marks {name}"
        t.lap("records")
        new_global: dict[str, set[str]] = {}  # unit -> units compiled in its run
        owners_before = set(anchor_owners(a, state))
        with committing(canon, state, [s.name for s in specs]):  # journal (C7)
            for view, recs, compiled in zip(views, all_recs, compiled_by_run, strict=True):
                for seg in compiled:
                    if recs.fact(seg, "G") and not state.fact(seg, "G"):
                        new_global[seg] = compiled
                commit_run(a, ctx.layout, state, view, compiled)  # also the facts
                self._attribute(view, compiled)
            owners = anchor_owners(a, state)
            for owner, uses in owners.items():
                for reader, command, line in uses:
                    self._warn(_anchor_warning(a, owner, reader, command, line))
            new_owners = sorted(set(owners) - owners_before, key=position)
            exported = self._pictures(views, compiled_by_run, pre)
            t.lap("commit")
            lists_complete = commit_lists(a, ctx.layout, state, views)
            t.lap("lists")
            full_run = next(
                (v for v, s in zip(views, specs, strict=True) if s.selection is None), None
            )
            tools = run_tools(a, ctx.layout, ctx.dist, env, state, views, full_run)
            t.lap("tools")
            post = self._view = read_canon(a, canon, state.list_suffixes)
            derived = tuple(f"{ctx.job}{x}" for x in derived_suffixes(state.list_suffixes))
            for recs, compiled in zip(all_recs, compiled_by_run, strict=True):
                for seg in compiled:
                    scan = self.sources.scan(seg)
                    # the list files it typesets (by command), reads (F records) and starts
                    # (L records: also \@starttoc in a class macro, e.g. a preface command)
                    reads = scan.list_reads()
                    if reads is not None:
                        reads |= {
                            f[f.rindex(ctx.job) + len(ctx.job) :]
                            for s, f in recs.files
                            if s == seg and f.endswith(derived)
                        }
                        reads |= {"." + ext for (ext,) in recs.fact(seg, "L")}
                    state.units[seg] = UnitInputs(
                        entry=recs.entry_state(seg),
                        imports=imports(scan, pre.values),
                        lists=pre.lists_key(reads) if reads is None or reads else None,
                        self_stable=pre_self[seg] == post.unit_self(seg),
                        list_reads=None if reads is None else sorted(reads),
                    )
                    changed = set(pre_self[seg]) ^ set(post.unit_self(seg))
                    self.rules.self_changes[seg] = sorted({command_name(s) for s in changed})
            state.glue_inputs = pre_glue
            last = all_recs[-1]
            self.schedule.last_entries = {
                seg: normalized(last.entry_state(seg)) for seg in last.entries
            }
            dirty_after, glue_after = self.rules.after_run(last, all_compiled, pre, post)
            if parallel:
                dirty_after, glue_after = self.schedule.verify(
                    groups, all_recs, pred, dirty_after, glue_after
                )
            if not lists_complete:
                glue_after = glue_after or "list files without unit markers (rewritten by the glue)"
            for g, with_g in new_global.items():
                # later units committed from runs without it miss its page numbering/style
                what = ", ".join(c for (c,) in state.fact(g, "G"))
                for seg in a.unit_segments[a.unit_segments.index(g) + 1 :]:
                    if seg not in with_g:
                        dirty_after.setdefault(seg, []).append(
                            f"after {a.include_of(g).arg}, which changes {what} at run time"
                        )
            for owner in new_owners:
                # a later segment uses its anchor: segments committed from runs without it
                # (the glue: the last run) used an older anchor
                with_o = next((c for c in compiled_by_run if owner in c), set())
                why = f"after {a.include_of(owner).arg}, whose anchor a later part uses"
                for seg in a.unit_segments[a.unit_segments.index(owner) + 1 :]:
                    if seg not in with_o:
                        dirty_after.setdefault(seg, []).append(why)
                if owner not in compiled_by_run[-1]:
                    glue_after = glue_after or why
            for seg, n in sorted(exported.items()):
                # the run typeset these pictures inline; embedded, the result equals externalize
                if is_unit(seg):
                    dirty_after.setdefault(seg, []).append(f"pictures exported ({n})")
                else:
                    glue_after = glue_after or f"pictures exported ({n} in the glue)"
            state.pending, state.glue_pending = dirty_after, glue_after
        t.lap("dirty")
        reports = []
        for j, (spec, result) in enumerate(zip(specs, results, strict=True)):
            reports.append(
                {
                    "name": spec.name,
                    "batch": number,
                    "selection": None if spec.selection is None else list(spec.selection),
                    "reasons": {
                        a.include_of(s).arg: r
                        for s, r in sorted(dirty.items())
                        if s in compiled_by_run[j]
                    },
                    "glue": glue,
                    "tools": tools if j == len(specs) - 1 else [],
                    "seconds": round(result.seconds, 2),
                    "tex": tex_phases(all_recs[j], result.seconds),
                    "glue_segments": glue_times(all_recs[j]),
                }
            )
        return reports

    def _pictures(
        self, views: list[RunView], compiled_by_run: list[set[str]], pre: CanonView
    ) -> dict[str, int]:
        """Export the figures of pictures typeset inline (§6.17) with the values of the keys
        their code references (``pre``: the runs' input), and record the figure keys per
        committed segment (units from their run, glue from the last run). Returns the number
        of exported pictures per segment."""
        ctx, state = self.ctx, self.state
        fig = ctx.layout.fig_dir if ctx.config.picture_cache else None
        glue = self.a.glue_segments
        exported: dict[str, int] = {}
        if fig is None:
            return exported
        for view, compiled in zip(views, compiled_by_run, strict=True):
            pics = parse_pictures(view.log)
            export_run(fig, view.file(".pdf"), pics, pre.values, self.a.source_dir)
            for seg in [*compiled, *glue]:
                state.pictures[seg] = sorted({p.key for p in pics if p.segment == seg})
            for p in pics:
                if p.exported:
                    exported[p.segment] = exported.get(p.segment, 0) + 1
        if exported:
            record_inputs(fig, state.dist_files)
        return exported

    def _attribute(self, run: RunView, compiled: set[str]) -> None:
        """Source files of the compiled units and the glue (F records), global inputs."""
        ctx, state = self.ctx, self.state
        new_files = _segment_files(ctx, run.records)
        for seg in [*compiled, *self.a.glue_segments]:
            state.segment_files[seg] = new_files.get(seg, {})
        self.sources.forget([*compiled, *self.a.glue_segments])
        attributed = {n for files in state.segment_files.values() for n in files}
        state.global_files = {
            n: h
            for n, h in {
                **state.global_files,
                **_global_files(ctx, run, attributed),
                **format_inputs(ctx.layout),  # read by the format build, not by the runs
            }.items()
            if n not in attributed
        }
        fls = run.file(".fls")
        state.dist_files.update(format_dist_inputs(ctx.layout))
        state.dist_files.update(
            dist_signatures(fls, ctx.layout.shadow_dir, ctx.layout.internal_dirs)
        )

    def _canon_records(self, canon: Path) -> RunRecords:
        """Header records of the canonical main aux (counters, layout)."""
        return read_main_records(canon / f"{self.ctx.job}.aux")

    def converge(self, dirty: dict[str, list[str]], glue: str | None) -> list[dict[str, Any]]:
        """Iterate batches until nothing is dirty and the glue is valid (§6.9.2)."""
        runs: list[dict[str, Any]] = []
        for iteration in range(MAX_ITERATIONS):
            if not dirty and glue is None:
                return runs
            selection, reasons = self.schedule.plan(dirty)
            for seg, why in sorted(reasons.items(), key=lambda x: position(x[0])):
                arg = self.a.include_of(seg).arg
                self.ctx.say(f"dirty {arg}: {'; '.join(why)}")
            if glue is not None:
                self.ctx.say(f"glue: {glue}")
            runs += self.batch(self.schedule.groups(selection), reasons, glue, iteration)
            dirty, glue = self.state.pending, self.state.glue_pending
        if not dirty and glue is None:
            return runs
        raise FallbackError(f"no fixpoint after {MAX_ITERATIONS} iterations")


# --- entry point -----------------------------------------------------------------------------


def _gc(ctx: Context, state: State) -> None:
    if ctx.config.keep_runs or not ctx.layout.runs_dir.is_dir():
        return
    keep = state.run_names()
    for d in ctx.layout.runs_dir.iterdir():
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d)


def _full(ctx: Context, epoch: int, reason: str, start: float) -> BuildReport:
    """Full mode with the epoch of the canonical state if there is one (N4, C11): the same
    dates as ``--full`` and the ``check`` reference, also for a fallback."""
    epoch = load_epoch(ctx.layout.canon_dir, epoch)
    ctx.say(f"full build: {reason}")
    result = full_build(
        ctx.analysis,
        ctx.layout,
        ctx.dist,
        ctx.dist.environment(epoch, ctx.base_env),
        report=ctx.say,
        picture_cache=ctx.config.picture_cache,
    )
    ctx.timings.lap("full")
    return BuildReport(
        "full",
        reason,
        [{"name": "full", "selection": None, "passes": result.passes}],
        [inc.arg for inc in ctx.analysis.includes],
        time.monotonic() - start,
        str(result.pdf),
        # a fallback is reported as a warning (§6.14), --full is not
        warnings=[] if reason == "--full" else [f"full build: {reason}"],
        timings=ctx.timings.as_dict(),
    )


def _cold_reason(ctx: Context, state: State | None, stamp: str) -> str | None:
    stopped = journal_reason(ctx.layout.canon_dir)
    if stopped is not None:
        return stopped
    if state is None:
        return "no previous state"
    if state.format_stamp != stamp:
        return "preamble (format part), TeX installation or chapmk version changed"
    changed_dist = changed_signatures(state.dist_files)
    if changed_dist:
        names = [Path(p).name for p in changed_dist]
        return f"TeX distribution files changed ({short_list(names)})"
    if state.fingerprints != asdict(ctx.analysis.fingerprints):
        return "main file changed (preamble or body)"
    if state.includes != [inc.arg for inc in ctx.analysis.includes]:
        return "list of includes changed"
    changed = changed_files(ctx.analysis.source_dir, state.global_files)
    if changed:
        return f"global inputs changed ({short_list(changed)})"
    return None


def _sync_shadow(ctx: Context) -> None:
    """Bring the shadow tree up to date; list files found by earlier builds are build outputs
    too (excluded)."""
    try:
        state = load_state(ctx.layout.canon_dir)
    except CorruptStateError:
        state = None  # the build starts cold and says why
    suffixes = state.list_suffixes if state is not None else ()
    sync_project_shadow(ctx.analysis, ctx.layout.shadow_dir, ctx.layout.build_dir, suffixes)
    ctx.timings.lap("shadow")


def build(ctx: Context, epoch: int, *, full: bool = False) -> BuildReport:
    """Build the document: full mode, or the fixpoint loop (cold or incremental) (§5). The
    shadow tree is synchronised first (also for the ``check`` reference that follows)."""
    start = time.monotonic()
    canon = ctx.layout.canon_dir
    _sync_shadow(ctx)
    if full:
        return _full(ctx, epoch, "--full", start)
    if ctx.analysis.fallback_reasons:
        return _full(ctx, epoch, "; ".join(ctx.analysis.fallback_reasons), start)
    marker = canon / FULL_ONLY_FILE
    # keyed by the version too: an upgrade may support what forced full mode
    stamp_data = {"fingerprints": asdict(ctx.analysis.fingerprints), "chapmk": chapmk.__version__}
    try:
        data = json.loads(marker.read_bytes()) if marker.is_file() else {}
    except (OSError, ValueError):
        data = {}  # unreadable: ignored (attempt the incremental build)
    if (
        isinstance(data, dict)
        and "reason" in data
        and all(data.get(k) == v for k, v in stamp_data.items())
    ):
        return _full(ctx, epoch, data["reason"], start)
    try:
        try:
            state = load_state(canon)
            unreadable = None
        except CorruptStateError as err:  # E7: a cold build instead of an error
            state, unreadable = None, str(err)
        stamp = format_stamp(ctx.analysis, ctx.dist.version)
        reason = _cold_reason(ctx, state, stamp) if unreadable is None else unreadable
        if state is None or reason is not None:
            ctx.say(f"cold build: {reason}")
            next_run = state.next_run if state is not None else 1
            if canon.exists():
                shutil.rmtree(canon)
            state = State(
                epoch=epoch,
                fingerprints=asdict(ctx.analysis.fingerprints),
                format_stamp=stamp,
                includes=[inc.arg for inc in ctx.analysis.includes],
                segments={},
                next_run=next_run,
            )
        ctx.timings.lap("state")
        try:
            fmt = ensure_format(ctx.analysis, ctx.layout, ctx.dist, ctx.env(state.epoch))
        except TexError as err:  # an unsupported package (loaded by the class) may cause it: pdfx
            why = unsupported_loaded(loaded_names(ctx.layout.fmt_dir / f"{FORMAT_NAME}.fls"))
            raise FallbackError(
                why or f"format build failed: {err.first_error}", bool(why)
            ) from err
        loop = Fixpoint(ctx, state, fmt)
        if reason is not None:
            dirty: dict[str, list[str]] = {seg: ["cold build"] for seg in loop.units}
            glue: str | None = "cold build"
        else:
            dirty, glue = loop.rules.initial()
        ctx.timings.lap("format")
        runs = loop.converge(dirty, glue)
        slow_glue: dict[str, float] = {}
        for r in runs:
            for seg, seconds in r.get("glue_segments", {}).items():
                slow_glue[seg] = max(slow_glue.get(seg, 0.0), seconds)
        hints = glue_hints(
            ctx.analysis.main.name,
            ctx.analysis.lines,
            ctx.analysis.begin_line,
            [inc.line for inc in ctx.analysis.includes],
            slow_glue,
            [*UNIT_HEADINGS, *ctx.config.unit_headings],
        )
        for hint in hints:
            ctx.say(f"hint: {hint}")
        if runs:  # a no-op build lints nothing
            save_lint_cache(canon, loop.sources.lint_cache)
        if runs or not is_published(ctx.layout):
            pdf = publish_state(
                ctx.analysis, ctx.layout, state, ctx.timings, dist=ctx.dist, views=loop.views
            )
            mark_published(ctx.layout)
        else:  # nothing changed: the published files are current (latexmk-like no-op)
            pdf = ctx.layout.output(".pdf")
        _gc(ctx, state)
        if ctx.config.picture_cache:
            collect_garbage(
                ctx.layout.fig_dir, {k for keys in state.pictures.values() for k in keys}
            )
        ctx.timings.lap("gc")
        compiled: set[str] = set()
        for r in runs:
            if r["selection"] is None:
                compiled.update(inc.arg for inc in ctx.analysis.includes)
            else:
                compiled.update(r["selection"])
        mode = "cold" if reason is not None else "incremental" if runs else "noop"
        return BuildReport(
            mode,
            reason,
            runs,
            [inc.arg for inc in ctx.analysis.includes if inc.arg in compiled],
            time.monotonic() - start,
            str(pdf),
            loop.warnings,
            ctx.timings.as_dict(),
            hints,
        )
    except FallbackError as fb:
        if fb.persistent:
            canon.mkdir(parents=True, exist_ok=True)
            write_atomic(marker, json.dumps({**stamp_data, "reason": str(fb)}))
        return _full(ctx, epoch, str(fb), start)


def load_epoch(canon_dir: Path, default: int) -> int:
    """SOURCE_DATE_EPOCH of the canonical state (N4), else ``default``."""
    try:
        state = load_state(canon_dir)
    except CorruptStateError:
        return default
    return state.epoch if state is not None else default
