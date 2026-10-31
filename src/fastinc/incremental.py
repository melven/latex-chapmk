"""Incremental builder (PLAN §5, §6.9; M4): full mode for fallback reasons, otherwise the
fixpoint loop.

Each iteration compiles the dirty compilation units (all units: a full run; none: a glue-only
run) together with the glue in one run, commits the result into the canonical state
(:mod:`fastinc.canon`) and recomputes the dirty set from the dependency model (§6.8):

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

import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastinc.analysis import Analysis
from fastinc.aux import AGGREGATE, GLOBAL, command_name, read_lines, run_input_main_aux, statements
from fastinc.canon import CanonView, commit_run, read_canon, segments
from fastinc.config import Config
from fastinc.deps import TokenScan, changed_imports, imports, read_text, short_hash
from fastinc.errors import FastincError, TexError
from fastinc.fmt import FormatInfo, ensure_format, format_stamp
from fastinc.fullbuild import full_build, read_inputs
from fastinc.layout import Layout
from fastinc.lint import LintHit, lint_files
from fastinc.outputs import MergeFailedError, failed_run, publish_state
from fastinc.records import RecordError, RunRecords, read_run_records, register_names
from fastinc.runner import DERIVED_SUFFIXES, RunSpec, prepare_run_dir, run_one
from fastinc.state import State, UnitInputs, load_state, save_state
from fastinc.texdist import TexDistribution
from fastinc.tools import ToolInputError

MAX_ITERATIONS = 8
#: Packages that force full mode when loaded at all (also by the class; seen in the .fls).
RUNTIME_UNSUPPORTED = (
    "imakeidx.sty",
    "makeidx.sty",
    "glossaries.sty",
    "cleveref.sty",
    "minted.sty",
)
FULL_ONLY_FILE = "full-only.json"


class FallbackError(FastincError):
    """The incremental machinery cannot handle this build; use full mode (§6.14).
    ``persistent``: the reason holds until the main file changes (skip the attempt next time)."""

    def __init__(self, message: str, persistent: bool = False):
        super().__init__(message)
        self.persistent = persistent


@dataclass
class BuildReport:
    """What a build did (``fastinc build --report``): mode, reason, runs (with selection and
    dirty reasons), compiled includes, lint warnings."""

    mode: str  # "full", "cold", "incremental" or "noop"
    reason: str | None = None
    runs: list[dict[str, Any]] = field(default_factory=list)
    compiled: list[str] = field(default_factory=list)
    seconds: float = 0.0
    pdf: str | None = None
    warnings: list[str] = field(default_factory=list)

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

    @property
    def job(self) -> str:
        return self.analysis.jobname

    def env(self, epoch: int) -> dict[str, str]:
        return self.dist.environment(epoch, self.base_env, self.layout.fmt_dir)


# --- file attribution ------------------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    return {n: _sha(ctx.analysis.source_dir / n) for n in sorted(names)}


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
        rel = path.relative_to(ctx.layout.shadow_dir.resolve()).as_posix()
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
    for name, digest in files.items():
        path = ctx.analysis.source_dir / name
        if not path.is_file() or _sha(path) != digest:
            out.append(name)
    return out


def _check_runtime_support(ctx: Context, run_dir: Path, fmt: FormatInfo) -> None:
    """Packages loaded by the format or the run (also those loaded by the class)."""
    loaded: set[str] = set()
    for fls in (fmt.directory / f"{fmt.name}.fls", run_dir / f"{ctx.job}.fls"):
        if fls.is_file():
            lines = fls.read_text(errors="replace").splitlines()
            loaded |= {Path(line[6:]).name for line in lines if line.startswith("INPUT ")}
    for pkg in RUNTIME_UNSUPPORTED:
        if pkg in loaded:
            raise FallbackError(f"package {pkg[:-4]!r} is not supported (loaded at runtime)", True)
    if "hyperref.sty" in loaded and "bookmark.sty" not in loaded:
        raise FallbackError(
            "hyperref without the bookmark package (outline via .out is phase 2)", True
        )


def _records(ctx: Context, run_dir: Path) -> RunRecords:
    try:
        return read_run_records(run_dir, ctx.analysis)
    except RecordError as err:
        raise FallbackError(f"records: {err}") from err


def _short(items: list[str], limit: int = 3) -> str:
    shown = ", ".join(items[:limit])
    return shown if len(items) <= limit else f"{shown}, ... (+{len(items) - limit})"


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
        self.warnings: list[str] = []
        self.register_names: dict[int, str] = {}  # for messages, from the logs

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
            self._lint[seg] = lint_files(
                self.a.source_dir, self.state.segment_files.get(seg, {}), self.ctx.config.lint_allow
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
                dirty.setdefault(seg, []).append(f"sources changed ({_short(changed)})")
        glue = self.state.glue_pending
        changed = self._glue_sources_changed()
        if changed:
            glue = f"glue sources changed ({_short(changed)})"
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
            msg = f"unclassified aux data changed ({_short(names)})"
            self._warn(f"{msg}: all units are recompiled; please report these macros")
            for seg in self.units:
                add(seg, msg)
        if set(pre.of_class(AGGREGATE)) != set(post.of_class(AGGREGATE)):
            for seg in self.units:
                add(seg, "aggregate aux data changed (e.g. KOMA autodot)")
        eqp_pre, eqp_post = pre.eqp(), post.eqp()
        if any(eqp_pre.get(k) != v for k, v in eqp_post.items()):
            for seg in sorted(compiled):
                add(seg, "eqparbox widths changed")
        for seg in self.units:
            info = self.state.units.get(seg)
            if info is None:
                add(seg, "never compiled")
                continue
            if seg in compiled and not info.self_stable:
                add(seg, "self data unstable (rerun)")
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
                    add(seg, f"entry state changed ({_short(shown)})")
            keys = changed_imports(info.imports, self.scan(seg), post.values)
            if keys:
                add(seg, f"imports changed ({_short(keys)})")
            if info.lists is not None and info.lists != post.lists:
                add(seg, "list files changed")
            changed = _changed(self.ctx, self.state.segment_files.get(seg, {}))
            if changed:
                add(seg, f"sources changed ({_short(changed)})")
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
            glue = f"glue sources changed ({_short(changed)})"
        return dirty, glue

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

    def run(
        self, selection: list[int] | None, dirty: Mapping[str, list[str]], glue: str | None
    ) -> dict[str, Any]:
        """Compile ``selection`` plus glue in one run and commit it."""
        ctx, a, state = self.ctx, self.a, self.state
        name = state.new_run_name()
        ks = list(range(1, len(self.units) + 1)) if selection is None else selection
        args = None if selection is None else tuple(a.includes[k - 1].arg for k in ks)
        compiled = {f"U{k}" for k in ks}
        for seg in sorted(compiled, key=lambda s: int(s[1:])):
            for hit in self.lint(seg):
                self._warn(hit.message())
        what = "all units" if args is None else ", ".join(args) if args else "glue only"
        ctx.say(f"run {name}: {what}")
        canon = ctx.layout.canon_dir
        spec = RunSpec(name, args)
        run_dir = prepare_run_dir(
            a,
            ctx.layout,
            spec,
            canon_dir=canon if canon.is_dir() else None,
            deny_names=ctx.config.state_ignore,
        )
        main_aux = run_dir / f"{ctx.job}.aux"
        if main_aux.is_file():
            excluded = {seg for seg in self.units if seg not in compiled}
            stmts = run_input_main_aux(statements(read_lines(main_aux)), excluded)
            main_aux.write_text("\n".join(stmts) + "\n", encoding="utf-8", errors="surrogateescape")
        pre = read_canon(a, canon)
        pre_glue = self.glue_inputs(pre)
        pre_self = {seg: pre.unit_self(seg) for seg in compiled}
        env = ctx.env(state.epoch)
        result = run_one(a, ctx.layout, ctx.dist, env, spec, self.fmt.name)
        if not result.ok:
            raise failed_run(
                a, ctx.layout, run_dir, TexError("pdflatex failed", first_error=result.first_error)
            )
        recs = _records(ctx, run_dir)
        _check_runtime_support(ctx, run_dir, self.fmt)
        if not self.register_names:
            self.register_names = register_names(
                [self.fmt.directory / f"{self.fmt.name}.log", run_dir / f"{ctx.job}.log"]
            )
        try:
            tools = commit_run(a, ctx.layout, ctx.dist, env, state, name, recs, compiled)
        except ToolInputError as err:
            raise FallbackError(str(err)) from err
        new_files = _segment_files(ctx, recs)
        for seg in [*compiled, *(g for g in segments(a) if g.startswith("G"))]:
            state.segment_files[seg] = new_files.get(seg, {})
            self._scans.pop(seg, None)
            self._lint.pop(seg, None)
        self._scans.pop("glue", None)
        attributed = {n for files in state.segment_files.values() for n in files}
        state.global_files = {
            n: h
            for n, h in {**state.global_files, **_global_files(ctx, run_dir, attributed)}.items()
            if n not in attributed
        }
        post = read_canon(a, canon)
        derived = tuple(f"{ctx.job}{s}" for s in DERIVED_SUFFIXES)
        for seg in compiled:
            scan = self.scan(seg)
            reads = scan.reads_lists() or any(
                s == seg and f.endswith(derived) for s, f in recs.files
            )
            state.units[seg] = UnitInputs(
                entry=recs.entry_state(seg),
                imports=imports(scan, pre.values),
                lists=pre.lists if reads else None,
                self_stable=pre_self[seg] == post.unit_self(seg),
            )
        state.glue_inputs = pre_glue
        state.pending, state.glue_pending = self.after_run(recs, compiled, pre, post)
        save_state(state, canon)
        return {
            "name": name,
            "selection": None if args is None else list(args),
            "reasons": {a.includes[int(s[1:]) - 1].arg: r for s, r in sorted(dirty.items())},
            "glue": glue,
            "tools": tools,
            "seconds": round(result.seconds, 2),
        }

    def converge(self, dirty: dict[str, list[str]], glue: str | None) -> list[dict[str, Any]]:
        """Run until nothing is dirty and the glue is valid (§6.9.2)."""
        runs: list[dict[str, Any]] = []
        for _ in range(MAX_ITERATIONS):
            if not dirty and glue is None:
                return runs
            selection, reasons = self.plan(dirty)
            for seg, why in sorted(reasons.items(), key=lambda x: int(x[0][1:])):
                arg = self.a.includes[int(seg[1:]) - 1].arg
                self.ctx.say(f"dirty {arg}: {'; '.join(why)}")
            if glue is not None:
                self.ctx.say(f"glue: {glue}")
            runs.append(self.run(selection, reasons, glue))
            dirty, glue = self.state.pending, self.state.glue_pending
        if not dirty and glue is None:
            return runs
        raise FallbackError(f"no fixpoint after {MAX_ITERATIONS} runs")


# --- entry point -----------------------------------------------------------------------------


def _gc(ctx: Context, state: State) -> None:
    if ctx.config.keep_runs or not ctx.layout.runs_dir.is_dir():
        return
    keep = state.run_names()
    for d in ctx.layout.runs_dir.iterdir():
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d)


def _full(ctx: Context, epoch: int, reason: str, start: float) -> BuildReport:
    ctx.say(f"full build: {reason}")
    result = full_build(
        ctx.analysis,
        ctx.layout,
        ctx.dist,
        ctx.dist.environment(epoch, ctx.base_env),
        report=ctx.say,
    )
    return BuildReport(
        "full",
        reason,
        [{"name": "full", "selection": None, "passes": result.passes}],
        [inc.arg for inc in ctx.analysis.includes],
        time.monotonic() - start,
        str(result.pdf),
    )


def _cold_reason(ctx: Context, state: State | None, stamp: str) -> str | None:
    if state is None:
        return "no previous state"
    if state.format_stamp != stamp:
        return "preamble (format part) or TeX installation changed"
    if state.fingerprints != asdict(ctx.analysis.fingerprints):
        return "main file changed (preamble or body)"
    if state.includes != [inc.arg for inc in ctx.analysis.includes]:
        return "list of includes changed"
    changed = _changed(ctx, state.global_files)
    if changed:
        return f"global inputs changed ({_short(changed)})"
    return None


def build(ctx: Context, epoch: int, *, full: bool = False) -> BuildReport:
    """Build the document: full mode, or the fixpoint loop (cold or incremental) (§5)."""
    start = time.monotonic()
    canon = ctx.layout.canon_dir
    if full:
        return _full(ctx, load_epoch(canon, epoch), "--full", start)
    if ctx.analysis.fallback_reasons:
        return _full(ctx, epoch, "; ".join(ctx.analysis.fallback_reasons), start)
    marker = canon / FULL_ONLY_FILE
    stamp_data = {"fingerprints": asdict(ctx.analysis.fingerprints)}
    if marker.is_file():
        data = json.loads(marker.read_text())
        if data.get("fingerprints") == stamp_data["fingerprints"]:
            return _full(ctx, epoch, data["reason"], start)
    try:
        state = load_state(canon)
        stamp = format_stamp(ctx.analysis, ctx.dist.version)
        reason = _cold_reason(ctx, state, stamp)
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
        runs = loop.converge(dirty, glue)
        pdf = publish_state(ctx.analysis, ctx.layout, state)
        _gc(ctx, state)
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
        )
    except (FallbackError, MergeFailedError) as fb:
        if isinstance(fb, FallbackError) and fb.persistent:
            canon.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({**stamp_data, "reason": str(fb)}))
        return _full(ctx, epoch, str(fb), start)


def load_epoch(canon_dir: Path, default: int) -> int:
    """SOURCE_DATE_EPOCH of the canonical state (N4), else ``default``."""
    state = load_state(canon_dir)
    return state.epoch if state is not None else default
