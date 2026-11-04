"""Incremental builder (PLAN §5, §6.9; M4): full mode for fallback reasons, otherwise the
fixpoint loop.

Each iteration compiles the dirty compilation units (all units: a full run; none: a glue-only
run) together with the glue in one run, commits the result into the canonical state
(:mod:`chapmk.canon`) and recomputes the dirty set from the dependency model (§6.8):

- a unit is dirty if its sources changed, an imported label or citation value changed, its
  self data was unstable, its observed entry state changed or it follows such a unit (tail
  run: without prediction, M5, the later units are compiled in the same run), unclassified
  or aggregate aux data changed, or a list file it typesets changed; *global* units (lint,
  §6.8.4) are compiled in every run, and with all later units when they are dirty;
- the glue (compiled in every run) is valid if its inputs (derived files, imported values,
  glue aux data, glue sources) equal those the committed glue run started from.

The loop ends when nothing is dirty and the glue is valid (then every committed segment was
compiled from the final canonical state); otherwise after :data:`MAX_ITERATIONS` runs the
build falls back to full mode. A cold build is the same loop starting with all units dirty
and an empty canonical state (§6.9.4).
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import chapmk
from chapmk.analysis import Analysis
from chapmk.aux import AGGREGATE, GLOBAL, command_name, read_lines, run_input_main_aux, statements
from chapmk.canon import CanonView, commit_lists, commit_run, read_canon, run_tools, segments
from chapmk.config import Config
from chapmk.deps import TokenScan, changed_imports, imports, read_text, short_hash
from chapmk.errors import FallbackError, TexError
from chapmk.facts import UNIT_HEADINGS, UNSUPPORTED_PACKAGES, derived_suffixes
from chapmk.files import digest, write_atomic
from chapmk.fmt import (
    FormatInfo,
    ensure_format,
    format_dist_inputs,
    format_inputs,
    format_stamp,
    internal_dirs,
)
from chapmk.fullbuild import full_build
from chapmk.layout import Layout
from chapmk.lint import LintHit, glue_hints, lint_files
from chapmk.logs import short_list
from chapmk.outputs import (
    failed_run,
    is_published,
    mark_published,
    publish_state,
)
from chapmk.pictures import (
    PICS_FILE,
    check_inputs,
    collect_garbage,
    driver_file,
    export_figures,
    read_pictures,
    record_inputs,
    remove_figures,
    stale_figures,
    store_references,
)
from chapmk.predict import (
    SegmentVectors,
    Vector,
    modified,
    normalized,
    partition,
    predict,
    rewrite_checkpoint,
)
from chapmk.records import (
    RunRecords,
    glue_times,
    read_main_records,
    read_run_records,
    register_names,
    tex_phases,
)
from chapmk.runner import RunSpec, prepare_run_dir, run_batch
from chapmk.shadow import changed_signatures, external_inputs, read_inputs, stat_signatures
from chapmk.state import CorruptStateError, State, UnitInputs, load_state, save_state
from chapmk.texdist import TexDistribution
from chapmk.texsource import text_lines
from chapmk.timing import Timings

MAX_ITERATIONS = 8
FULL_ONLY_FILE = "full-only.json"
#: present in ``canon/`` while a batch commits (C7)
JOURNAL_FILE = ".in-progress"


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
    timings: dict[str, float] = field(default_factory=dict)  # wall time per phase (M6)
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
    name = recorded.lstrip("/")
    name = name[2:] if name.startswith("./") else name
    if not name:
        return None
    shadow = ctx.layout.shadow_dir / name
    if shadow.is_file() and (ctx.analysis.source_dir / name).is_file():
        return Path(name).as_posix()
    return None


def _hashes(ctx: Context, names: set[str]) -> dict[str, str]:
    return {n: digest(ctx.analysis.source_dir / n) for n in sorted(names)}


def _segment_files(ctx: Context, recs: RunRecords) -> dict[str, dict[str, str]]:
    files: dict[str, set[str]] = {}
    for seg, recorded in recs.files:
        name = _source_file(ctx, recorded)
        if name is not None:
            files.setdefault(seg, set()).add(name)
    return {seg: _hashes(ctx, names) for seg, names in files.items()}


def _global_files(ctx: Context, run_dir: Path, attributed: set[str]) -> dict[str, str]:
    """Source files read by the run but attributed to no segment, plus biblatex data sources."""
    names: set[str] = set()
    for path in read_inputs(
        run_dir / f"{ctx.job}.fls", ctx.layout.shadow_dir, ctx.layout.shadow_dir
    ):
        rel = path.relative_to(Path(ctx.layout.shadow_dir).absolute()).as_posix()
        if (ctx.analysis.source_dir / rel).is_file() and rel not in attributed:
            names.add(rel)
    bcf = run_dir / f"{ctx.job}.bcf"
    if bcf.is_file():
        for m in re.finditer(r"<bcf:datasource[^>]*>([^<]+)</bcf:datasource>", bcf.read_text()):
            if (ctx.analysis.source_dir / m.group(1)).is_file():
                names.add(Path(m.group(1)).as_posix())
    return _hashes(ctx, names - attributed)


def _changed(ctx: Context, files: dict[str, str]) -> list[str]:
    out = []
    for name, stored in files.items():
        path = ctx.analysis.source_dir / name
        if not path.is_file() or digest(path) != stored:
            out.append(name)
    return out


def _check_runtime_support(ctx: Context, run_dir: Path, fmt: FormatInfo) -> None:
    """Packages loaded by the format or the run (also those loaded by the class)."""
    loaded: set[str] = set()
    for fls in (fmt.directory / f"{fmt.name}.fls", run_dir / f"{ctx.job}.fls"):
        if fls.is_file():
            lines = text_lines(fls.read_text(errors="replace"))
            loaded |= {Path(line[6:]).name for line in lines if line.startswith("INPUT ")}
    for pkg in sorted(UNSUPPORTED_PACKAGES):
        if f"{pkg}.sty" in loaded:
            raise FallbackError(f"package {pkg!r} is not supported (loaded at runtime)", True)
    if "hyperref.sty" in loaded and "bookmark.sty" not in loaded:
        raise FallbackError(
            "hyperref without the bookmark package (outline via .out is phase 2)", True
        )


def _write(path: Path, stmts: list[str]) -> None:
    write_atomic(path, "\n".join(stmts) + "\n")


def _eqp_tag(key: str) -> str:
    """``\\expandafter\\gdef\\csname eqp@this@T\\endcsname`` -> ``T``."""
    m = re.search(r"eqp@[a-z]+@(.*?)\\endcsname", key)
    return m.group(1) if m else key


def _lists_now(stored: str, view: CanonView) -> str:
    """The current value of a unit's stored list dependency (``.bbl,.toc=<hash>``, or the
    hash of all list files)."""
    if "=" not in stored:
        return view.lists
    names = stored.split("=", 1)[0]
    return view.lists_key(names.split(",") if names else [])


class _UsedCache(dict[str, list[list[Any]]]):
    """A cache that looks up ``old`` entries and holds only the entries used or added (saved
    after the build, so it does not grow with every edit)."""

    def __init__(self, old: dict[str, list[list[Any]]]) -> None:
        super().__init__()
        self.old = old

    def __contains__(self, key: object) -> bool:
        return dict.__contains__(self, key) or key in self.old

    def __getitem__(self, key: str) -> list[list[Any]]:
        if not dict.__contains__(self, key):
            self[key] = self.old[key]
        return dict.__getitem__(self, key)


LINT_CACHE = "lint-cache.json"


# --- the fixpoint loop -------------------------------------------------------------------------


class Fixpoint:
    """Dirty sets, runs and commits of one build (§6.9.2; one run per iteration, M4)."""

    def __init__(self, ctx: Context, state: State, fmt: FormatInfo) -> None:
        self.ctx, self.state, self.fmt = ctx, state, fmt
        self.a = ctx.analysis
        self.units = [f"U{k}" for k in range(1, len(self.a.includes) + 1)]
        index = {inc.arg: k for k, inc in enumerate(self.a.includes, start=1)}
        self.group: dict[int, list[int]] = {}
        for unit in self.a.units:
            ks = [index[inc.arg] for inc in unit.includes]
            for k in ks:
                self.group[k] = ks
        self._scans: dict[str, TokenScan] = {}
        self._lint: dict[str, list[LintHit]] = {}
        # lint results by file content (persistent: linting all units is the largest Python
        # cost of a typo build otherwise); only entries used by this build are saved
        try:
            old = json.loads((ctx.layout.canon_dir / LINT_CACHE).read_text())
        except (OSError, ValueError):
            old = {}
        self.lint_cache = _UsedCache(old if isinstance(old, dict) else {})
        self.warnings: list[str] = []
        self.register_names: dict[int, str] = {}  # for messages, from the logs
        self._view: CanonView | None = None  # canonical view after the last batch (unchanged since)
        self.last_entries: dict[str, Vector] = {}  # observed in the latest run
        self.mispredicted: dict[str, int] = {}  # consecutive mispredictions per unit
        self.state_before: dict[str, SegmentVectors] = {}
        self.odd: frozenset[str] = frozenset()  # units starting on an odd page (prediction)
        self.self_changes: dict[str, list[str]] = {}  # macros of changed self data (messages)

    # sources -------------------------------------------------------------------------------

    def _texts(self, seg: str) -> list[str]:
        texts = []
        for name in self.state.segment_files.get(seg, {}):
            text = read_text(self.a.source_dir / name)
            if text is not None:
                texts.append(text)
        return texts

    def scan(self, seg: str) -> TokenScan:
        """Token scan of a unit's attributed sources (``"glue"``: main file and glue files)."""
        if seg not in self._scans:
            if seg == "glue":
                texts = [read_text(self.a.main) or ""]
                for g in segments(self.a):
                    if g.startswith("G"):
                        texts += self._texts(g)
            else:
                texts = self._texts(seg)
            self._scans[seg] = TokenScan(texts)
        return self._scans[seg]

    def lint(self, seg: str) -> list[LintHit]:
        """A1 lint hits in the TeX sources attributed to a unit (§6.8.4)."""
        if seg not in self._lint:
            cfg = self.ctx.config
            self._lint[seg] = lint_files(
                self.a.source_dir,
                self.state.segment_files.get(seg, {}),
                cfg.lint_allow,
                cfg.lint_verbatim,
                cfg.lint_shortverb,
                self.lint_cache,
            )
        return self._lint[seg]

    def is_global(self, seg: str) -> bool:
        return bool(self.lint(seg))

    def glue_inputs(self, view: CanonView) -> str:
        """The glue's inputs (§6.8.2) as ``lists=..;labels=..;aux=..``."""
        values = imports(self.scan("glue"), view.values)
        parts = {
            "lists": view.lists,
            "labels": short_hash(json.dumps(sorted(values.items()))),
            "aux": short_hash("\n".join(view.glue_data())),
        }
        return ";".join(f"{k}={v}" for k, v in parts.items())

    def pictures_file(self, view: CanonView) -> str:
        """Driver parameters of the picture cache (§6.17) for runs from ``view``: directory and
        stamp (format, main file). Figures whose code references a label or citation that
        changed since their export are removed first (the picture is exported again)."""
        ctx = self.ctx
        if not ctx.config.picture_cache:
            return driver_file(None, ctx.layout.shadow_dir, "", {})
        fig = ctx.layout.fig_dir
        check_inputs(fig)  # package updates
        remove_figures(fig, stale_figures(fig, view.values, self.a.source_dir))
        stamp = short_hash(
            self.state.format_stamp + json.dumps(self.state.fingerprints, sort_keys=True)
        )
        return driver_file(fig, ctx.layout.shadow_dir, stamp, {})

    def _glue_sources_changed(self) -> list[str]:
        return [
            name
            for g in segments(self.a)
            if g.startswith("G")
            for name in _changed(self.ctx, self.state.segment_files.get(g, {}))
        ]

    # dirty sets ----------------------------------------------------------------------------

    def initial(self) -> tuple[dict[str, list[str]], str | None]:
        """Dirty units and glue at the start of an incremental build."""
        dirty = {seg: list(reasons) for seg, reasons in self.state.pending.items()}
        for seg in self.units:
            if seg not in self.state.units:
                dirty.setdefault(seg, []).append("never compiled")
                continue
            changed = _changed(self.ctx, self.state.segment_files.get(seg, {}))
            if changed:
                dirty.setdefault(seg, []).append(f"sources changed ({short_list(changed)})")
        glue = self.state.glue_pending
        changed = self._glue_sources_changed()
        if changed:
            glue = f"glue sources changed ({short_list(changed)})"
        return dirty, glue

    def after_run(
        self, recs: RunRecords, compiled: set[str], pre: CanonView, post: CanonView
    ) -> tuple[dict[str, list[str]], str | None]:
        """Dirty units and glue after committing a run (§6.9.1)."""
        dirty: dict[str, list[str]] = {}

        def add(seg: str, reason: str) -> None:
            dirty.setdefault(seg, []).append(reason)

        g_pre, g_post = pre.of_class(GLOBAL), post.of_class(GLOBAL)
        if g_pre != g_post:
            names = sorted({command_name(s) for s in set(g_pre) ^ set(g_post)})
            msg = f"unclassified aux data changed ({short_list(names)})"
            self._warn(f"{msg}: all units are recompiled; please report these macros")
            for seg in self.units:
                add(seg, msg)
        if set(pre.of_class(AGGREGATE)) != set(post.of_class(AGGREGATE)):
            for seg in self.units:
                add(seg, "aggregate aux data changed (e.g. KOMA autodot)")
        eqp_pre, eqp_post = pre.eqp(), post.eqp()
        tags = sorted({_eqp_tag(k) for k, v in eqp_post.items() if eqp_pre.get(k) != v})
        self._check_shared_tags(tags)
        if tags:
            # the units that use a changed tag (Q records); unknown owners: all compiled units
            owners = {
                seg for seg in self.units if set(tags) & set(self.state.eqp_tags.get(seg, ()))
            }
            known = {t for seg_tags in self.state.eqp_tags.values() for t in seg_tags}
            if not set(tags) <= known:
                owners |= compiled
            for seg in sorted(owners, key=lambda x: int(x[1:])):
                add(seg, f"eqparbox widths changed ({short_list(tags)})")
        for seg in self.units:
            info = self.state.units.get(seg)
            if info is None:
                add(seg, "never compiled")
                continue
            if seg in compiled and not info.self_stable:
                names = self.self_changes.get(seg, [])
                add(seg, f"self data unstable ({short_list(names) if names else 'rerun'})")
            if seg not in compiled and seg in recs.entries:
                entry = recs.entry_state(seg)
                counter = self.a.includes[int(seg[1:]) - 1].resets
                reset = recs.reset_registers(counter) if counter else set()
                regs = sorted(
                    r
                    for r in entry.keys() | info.entry.keys()
                    if r not in reset and entry.get(r) != info.entry.get(r)
                )
                if regs:
                    shown = [self.register_names.get(r, f"\\count{r}") for r in regs]
                    add(seg, f"entry state changed ({short_list(shown)})")
            keys = changed_imports(info.imports, self.scan(seg), post.values)
            if keys:
                add(seg, f"imports changed ({short_list(keys)})")
            if info.lists is not None and info.lists != _lists_now(info.lists, post):
                add(seg, "list files changed")
            changed = _changed(self.ctx, self.state.segment_files.get(seg, {}))
            if changed:
                add(seg, f"sources changed ({short_list(changed)})")
        # tail run (§6.9.2, no prediction in M4): recompiling a unit whose entry changed may
        # change its exit, so all later units are compiled with it, in one run
        moved = [
            i
            for i, seg in enumerate(self.units)
            if any(r.startswith("entry state changed") for r in dirty.get(seg, []))
        ]
        if moved:
            first = self.a.includes[moved[0]].arg
            for seg in self.units[moved[0] + 1 :]:
                add(seg, f"after {first}, whose entry state changed (tail run)")
        glue = None
        now = self.glue_inputs(post)
        if now != self.state.glue_inputs:
            old = dict(p.split("=", 1) for p in self.state.glue_inputs.split(";") if "=" in p)
            parts = [k for k, v in (p.split("=", 1) for p in now.split(";")) if old.get(k) != v]
            glue = f"glue inputs changed ({', '.join(parts)})"
        changed = self._glue_sources_changed()
        if changed:
            glue = f"glue sources changed ({short_list(changed)})"
        return dirty, glue

    def _check_shared_tags(self, changed: Sequence[str]) -> None:
        """C13: eqparbox sets all boxes of a tag to the widest one, computed from the boxes
        of one run. A tag used in several segments whose width changed while these were
        last compiled in different runs can differ from a full build: full mode."""
        for tag in changed:
            owners = [
                seg
                for seg in segments(self.a)
                if tag in self.state.eqp_tags.get(seg, ()) and seg in self.state.segments
            ]
            if len({self.state.segments[seg].run for seg in owners}) > 1:
                names = [self.a.includes[int(s[1:]) - 1].arg if s[0] == "U" else s for s in owners]
                raise FallbackError(
                    f"eqparbox tag {tag!r} is used in {', '.join(names)}: its width (the widest "
                    "box) changed, and a partial run sees only its own boxes (use the tag in one "
                    "chapter only, or one tag per chapter, to build incrementally)"
                )

    def _warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)
            self.ctx.say(f"warning: {msg}")

    # runs ----------------------------------------------------------------------------------

    def plan(self, dirty: Mapping[str, list[str]]) -> tuple[list[int] | None, dict[str, list[str]]]:
        """Include indices to compile (None = all) and the reasons per unit segment.

        Whole compilation units are compiled. A *global* unit (lint, §6.8.4) changes state
        that checkpoints do not restore, so it is part of every run; when it is dirty itself,
        all later units are compiled with it (they see its new state only in the same run).
        """
        reasons = {seg: list(r) for seg, r in dirty.items()}
        ks: set[int] = set()
        for seg in dirty:
            ks.update(self.group[int(seg[1:])])
        n = len(self.units)
        own = [k for k in sorted(ks) if self.is_global(f"U{k}")]
        if own:
            arg = self.a.includes[own[0] - 1].arg
            for k in range(own[0] + 1, n + 1):
                if k not in ks:
                    reasons[f"U{k}"] = [f"follows the global unit {arg} (lint)"]
                    ks.add(k)
        for k in range(1, n + 1):
            if k not in ks and self.is_global(f"U{k}"):
                reasons[f"U{k}"] = ["global unit (lint): compiled in every run for its state"]
                ks.update(self.group[k])
        return (None if len(ks) == n else sorted(ks)), reasons

    def groups(self, selection: list[int] | None) -> list[list[int] | None]:
        """Runs of one iteration: contiguous groups of the selected compilation units,
        balanced by page count, at most ``jobs`` (§6.9.2, M5). One run (the M4 tail run) if
        ``jobs`` is 1, a global unit exists (it would be compiled in every run), a unit has
        no vectors yet, or a unit of the zone was mispredicted twice in a row (§6.9.3 item 6).
        """
        ks = list(range(1, len(self.units) + 1)) if selection is None else selection
        jobs = self.ctx.config.effective_jobs
        atoms: list[list[int]] = []
        for k in ks:
            if atoms and self.group[k] is self.group[atoms[-1][0]]:
                atoms[-1].append(k)
            else:
                atoms.append([k])
        single = (
            jobs <= 1
            or len(atoms) <= 1
            or any(self.is_global(u) for u in self.units)
            or any(s not in self.state.vectors for s in segments(self.a)[2 * ks[0] - 1 :])
            or any(self.mispredicted.get(f"U{k}", 0) >= 2 for k in ks)
        )
        if single:
            return [selection]
        weights = [
            float(sum(max(1, len(self.state.segments[f"U{k}"].pages)) for k in atom))
            for atom in atoms
        ]
        return [[k for i in part for k in atoms[i]] for part in partition(weights, jobs)]

    def _predictions(
        self, groups: list[list[int]]
    ) -> tuple[
        dict[str, tuple[Vector, Vector]], dict[int, dict[str, tuple[Vector, frozenset[int]]]]
    ]:
        """Predicted (entry, exit) per segment from the first unit of the batch on, and per
        run index the checkpoints to write into its excluded units: predicted exit and the
        registers the unit modifies (only those are restored)."""
        first = f"U{groups[0][0]}"
        observed = self.last_entries.get(first)
        entry = observed if observed is not None else self.state.vectors[first].entry
        layout = self._canon_records(self.ctx.layout.canon_dir).layout
        default = bool(layout.get("twoside") and layout.get("openright"))
        chapter_level = {
            "part",
            "part*",
            "chapter",
            "chapter*",
            "addchap",
            "addchap*",
            "addpart",
            "addpart*",
        }
        # per unit as recorded at its start (a local open=any counts), else the document's
        odd = frozenset(
            f"U{k}"
            for k, inc in enumerate(self.a.includes, start=1)
            if inc.heading in chapter_level and self.state.openright.get(f"U{k}", default)
        )
        self.odd = odd
        pred = predict(segments(self.a), self.state.vectors, first, entry, odd)
        rewrites: dict[int, dict[str, tuple[Vector, frozenset[int]]]] = {}
        for j, group in enumerate(groups):
            out: dict[str, tuple[Vector, frozenset[int]]] = {}
            for k in range(groups[0][0], group[0]):
                seg = f"U{k}"
                out[seg] = (pred[seg][1], modified(self.state.vectors[seg]))
            rewrites[j] = out
        return pred, rewrites

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
            pred, rewrites = self._predictions([g for g in groups if g is not None])
            self.state_before = dict(state.vectors)  # verification uses the vectors predicted from
        t = ctx.timings
        t.lap("plan")  # dirty-set planning, groups, predictions
        registers = {n: reg for n, (reg, _) in self._canon_records(canon).counters.items()}
        pre = self._view if self._view is not None else read_canon(a, canon, state.list_suffixes)
        pre_glue = self.glue_inputs(pre)
        t.lap("canon")
        pictures_text = self.pictures_file(pre)
        t.lap("pictures")
        specs: list[RunSpec] = []
        compiled_by_run: list[set[str]] = []
        for j, group in enumerate(groups):
            name = state.new_run_name()
            ks = list(range(1, len(self.units) + 1)) if group is None else group
            args = None if group is None else tuple(a.includes[k - 1].arg for k in ks)
            compiled = {f"U{k}" for k in ks}
            for seg in sorted(compiled, key=lambda x: int(x[1:])):
                for hit in self.lint(seg):
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
                path = run_dir / a.includes[int(seg[1:]) - 1].aux_name
                stmts = rewrite_checkpoint(statements(read_lines(path)), exit_, registers, keep)
                _write(path, stmts)
            (run_dir / PICS_FILE).write_text(pictures_text, encoding="utf-8")
            specs.append(spec)
            compiled_by_run.append(compiled)
        all_compiled = set().union(*compiled_by_run)
        pre_self = {seg: pre.unit_self(seg) for seg in all_compiled}
        env = ctx.env(state.epoch)
        t.lap("prepare")  # run directories
        results = run_batch(a, ctx.layout, ctx.dist, env, specs, self.fmt.name, len(specs))
        t.lap("tex")
        for r in results:
            if not r.ok:
                err = TexError("pdflatex failed", first_error=r.first_error)
                raise failed_run(a, ctx.layout, r.directory, err)
        all_recs = [read_run_records(r.directory, ctx.analysis) for r in results]
        for recs in all_recs:  # list files with other extensions: stored and spliced from now on
            for suffix in sorted(recs.list_suffixes - set(state.list_suffixes)):
                state.list_suffixes.append(suffix)
        for r in results:
            _check_runtime_support(ctx, r.directory, self.fmt)
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
            self.register_names = register_names(
                [self.fmt.directory / f"{self.fmt.name}.log", results[0].log]
            )
            for reg, name in all_recs[0].mark_classes.items():
                self.register_names[reg] = f"marks {name}"
        t.lap("records")
        # journal (C7): canon files and state change from here until save_state; an
        # interrupted commit leaves the marker, and the next build is cold
        write_atomic(canon / JOURNAL_FILE, " ".join(s.name for s in specs))
        for spec, recs, compiled in zip(specs, all_recs, compiled_by_run, strict=True):
            commit_run(a, ctx.layout, state, spec.name, recs, compiled)
            self._attribute(recs, compiled, ctx.layout.runs_dir / spec.name)
            for seg in compiled:
                if seg in recs.openright:
                    state.openright[seg] = recs.openright[seg]
        exported = self._pictures(specs, compiled_by_run, pre)
        t.lap("commit")
        lists_complete = commit_lists(a, ctx.layout, state, specs[-1].name, [s.name for s in specs])
        t.lap("lists")
        tools = run_tools(
            a,
            ctx.layout,
            ctx.dist,
            env,
            state,
            specs[-1].name,
            [s.name for s in specs],
            full_run=next((s.name for s in specs if s.selection is None), None),
        )
        t.lap("tools")
        post = self._view = read_canon(a, canon, state.list_suffixes)
        derived = tuple(f"{ctx.job}{x}" for x in derived_suffixes(state.list_suffixes))
        for recs, compiled in zip(all_recs, compiled_by_run, strict=True):
            for seg in compiled:
                scan = self.scan(seg)
                # the list files it typesets (by command) and reads (F records)
                reads = scan.list_reads()
                if reads is not None:
                    reads |= {
                        f[f.rindex(ctx.job) + len(ctx.job) :]
                        for s, f in recs.files
                        if s == seg and f.endswith(derived)
                    }
                state.units[seg] = UnitInputs(
                    entry=recs.entry_state(seg),
                    imports=imports(scan, pre.values),
                    lists=pre.lists_key(reads) if reads is None or reads else None,
                    self_stable=pre_self[seg] == post.unit_self(seg),
                )
                changed = set(pre_self[seg]) ^ set(post.unit_self(seg))
                self.self_changes[seg] = sorted({command_name(s) for s in changed})
        state.glue_inputs = pre_glue
        last = all_recs[-1]
        self.last_entries = {seg: normalized(last.entry_state(seg)) for seg in last.entries}
        dirty_after, glue_after = self.after_run(last, all_compiled, pre, post)
        if parallel:
            dirty_after, glue_after = self._verify(groups, all_recs, pred, dirty_after, glue_after)
        if not lists_complete:
            glue_after = glue_after or "list files without unit markers (rewritten by the glue)"
        for seg, n in sorted(exported.items()):
            # the run typeset these pictures inline; embedded, the result equals externalize
            if seg.startswith("U"):
                dirty_after.setdefault(seg, []).append(f"pictures exported ({n})")
            else:
                glue_after = glue_after or f"pictures exported ({n} in the glue)"
        state.pending, state.glue_pending = dirty_after, glue_after
        save_state(state, canon)
        (canon / JOURNAL_FILE).unlink()
        t.lap("dirty")
        reports = []
        for j, (spec, result) in enumerate(zip(specs, results, strict=True)):
            reports.append(
                {
                    "name": spec.name,
                    "batch": number,
                    "selection": None if spec.selection is None else list(spec.selection),
                    "reasons": {
                        a.includes[int(s[1:]) - 1].arg: r
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

    def _verify(
        self,
        groups: list[list[int] | None],
        all_recs: list[RunRecords],
        pred: dict[str, tuple[Vector, Vector]],
        dirty: dict[str, list[str]],
        glue: str | None,
    ) -> tuple[dict[str, list[str]], str | None]:
        """§6.9.3 item 5: the exits of units whose predicted checkpoint later runs used must
        equal the prediction. At the first mismatch the glue is invalid (its pages come from
        the last run) and the later units whose start entry changes under the corrected
        prediction are dirty again, with all units after them."""
        dirty = {seg: list(r) for seg, r in dirty.items()}
        real = [g for g in groups if g is not None]
        for j, (group, recs) in enumerate(zip(real[:-1], all_recs[:-1], strict=True)):
            for k in group:
                seg = f"U{k}"
                actual = normalized(recs.checkpoints.get(seg, {}))
                entry = recs.entry_state(seg)
                keep = modified(self.state_before[seg])
                # registers the unit modifies match the predicted exit; all others must still
                # pass through (exit = entry)
                regs = sorted(
                    r
                    for r in actual.keys() | pred[seg][1].keys() | entry.keys()
                    if (
                        actual.get(r, 0) != pred[seg][1].get(r, 0)
                        if r in keep
                        else actual.get(r, 0) != entry.get(r, 0)
                    )
                )
                if not regs:
                    self.mispredicted.pop(seg, None)
                    continue
                self.mispredicted[seg] = self.mispredicted.get(seg, 0) + 1
                names = [self.register_names.get(r, f"\\count{r}") for r in regs]
                arg = self.a.includes[k - 1].arg
                reason = f"misprediction: exit of {arg} ({short_list(names)})"
                self.ctx.say(reason)
                # predict again from the actual exit: later runs were compiled with a wrong
                # entry only if the corrected chain changes their start entries (a later
                # absolute assignment, e.g. \\mainmatter for the page, absorbs the error);
                # the glue pages (last run) are redone in any case
                order = segments(self.a)
                nxt = order[order.index(seg) + 1]
                pred2 = predict(order, self.state_before, nxt, actual, self.odd)
                for later_group in real[j + 1 :]:
                    start = f"U{later_group[0]}"
                    if pred2[start][0] != pred[start][0]:
                        for later in range(later_group[0], len(self.units) + 1):
                            dirty.setdefault(f"U{later}", []).append(reason)
                        break
                return dirty, reason
        return dirty, glue

    def _pictures(
        self, specs: list[RunSpec], compiled_by_run: list[set[str]], pre: CanonView
    ) -> dict[str, int]:
        """Export the figures of pictures typeset inline (§6.17) with the values of the keys
        their code references (``pre``: the runs' input), and record the figure keys per
        committed segment (units from their run, glue from the last run). Returns the number
        of exported pictures per segment."""
        ctx, state = self.ctx, self.state
        fig = ctx.layout.fig_dir if ctx.config.picture_cache else None
        glue = [g for g in segments(self.a) if g.startswith("G")]
        exported: dict[str, int] = {}
        if fig is None:
            return exported
        for spec, compiled in zip(specs, compiled_by_run, strict=True):
            run_dir = ctx.layout.runs_dir / spec.name
            pics = read_pictures(run_dir / f"{ctx.job}.log")
            export_figures(run_dir / f"{ctx.job}.pdf", pics, fig)
            for seg in [*compiled, *glue]:
                state.pictures[seg] = sorted({p.key for p in pics if p.segment == seg})
            for p in pics:
                if p.exported:
                    store_references(fig, p, pre.values, self.a.source_dir)
                    exported[p.segment] = exported.get(p.segment, 0) + 1
        if exported:
            record_inputs(fig, state.dist_files)
        return exported

    def _attribute(self, recs: RunRecords, compiled: set[str], run_dir: Path) -> None:
        """Source files of the compiled units and the glue (F records), global inputs."""
        ctx, state = self.ctx, self.state
        new_files = _segment_files(ctx, recs)
        for seg in [*compiled, *(g for g in segments(self.a) if g.startswith("G"))]:
            state.segment_files[seg] = new_files.get(seg, {})
            self._scans.pop(seg, None)
            self._lint.pop(seg, None)
        self._scans.pop("glue", None)
        attributed = {n for files in state.segment_files.values() for n in files}
        state.global_files = {
            n: h
            for n, h in {
                **state.global_files,
                **_global_files(ctx, run_dir, attributed),
                **format_inputs(ctx.layout),  # read by the format build, not by the runs
            }.items()
            if n not in attributed
        }
        fls = run_dir / f"{ctx.job}.fls"
        state.dist_files.update(format_dist_inputs(ctx.layout))
        state.dist_files.update(
            stat_signatures(external_inputs(fls, ctx.layout.shadow_dir, internal_dirs(ctx.layout)))
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
            selection, reasons = self.plan(dirty)
            for seg, why in sorted(reasons.items(), key=lambda x: int(x[0][1:])):
                arg = self.a.includes[int(seg[1:]) - 1].arg
                self.ctx.say(f"dirty {arg}: {'; '.join(why)}")
            if glue is not None:
                self.ctx.say(f"glue: {glue}")
            runs += self.batch(self.groups(selection), reasons, glue, iteration)
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
    if (ctx.layout.canon_dir / JOURNAL_FILE).exists():
        return "the previous build was interrupted while committing"
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
    changed = _changed(ctx, state.global_files)
    if changed:
        return f"global inputs changed ({short_list(changed)})"
    return None


def build(ctx: Context, epoch: int, *, full: bool = False) -> BuildReport:
    """Build the document: full mode, or the fixpoint loop (cold or incremental) (§5)."""
    start = time.monotonic()
    canon = ctx.layout.canon_dir
    if full:
        return _full(ctx, epoch, "--full", start)
    if ctx.analysis.fallback_reasons:
        return _full(ctx, epoch, "; ".join(ctx.analysis.fallback_reasons), start)
    marker = canon / FULL_ONLY_FILE
    # keyed by the version too: an upgrade may support what forced full mode
    stamp_data = {"fingerprints": asdict(ctx.analysis.fingerprints), "chapmk": chapmk.__version__}
    try:
        data = json.loads(marker.read_text()) if marker.is_file() else {}
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
        except TexError as err:
            raise FallbackError(f"format build failed: {err.first_error}") from err
        loop = Fixpoint(ctx, state, fmt)
        if reason is not None:
            dirty: dict[str, list[str]] = {seg: ["cold build"] for seg in loop.units}
            glue: str | None = "cold build"
        else:
            dirty, glue = loop.initial()
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
            write_atomic(canon / LINT_CACHE, json.dumps(dict(loop.lint_cache)))
        if runs or not is_published(ctx.layout):
            pdf = publish_state(ctx.analysis, ctx.layout, state, ctx.timings)
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
