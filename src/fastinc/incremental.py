"""Incremental builder, M3 scope (PLAN §6.6, §6.9): cold builds, single-step incremental runs
with strict verification, merge and publish.

Correctness rule: a unit compiled alone is accepted only if everything it passes on to other
segments is byte-identical to the canonical state (its aux file, its main-aux slice, its
nomenclature entries). Then the glue and all other units are still valid. Otherwise a cold
build follows (M4 replaces this by the dependency model and the fixpoint).
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
from fastinc.aux import (
    bookmark_levels,
    content_lines,
    parse_bookmark,
    read_lines,
    segment_slices,
)
from fastinc.config import Config
from fastinc.errors import FastincError, TexError
from fastinc.fmt import FormatInfo, ensure_format, format_stamp
from fastinc.fullbuild import PassResult, converge, full_build, read_inputs
from fastinc.layout import Layout
from fastinc.logs import map_paths
from fastinc.merge_pdf import MergeError, OutlineEntry, PageSource, merge_pdf
from fastinc.publish import publish, text_writer
from fastinc.records import RecordError, RunRecords, read_nomenclature, read_run_records
from fastinc.runner import DERIVED_SUFFIXES, RUN_MAIN, RunSpec, prepare_run_dir, run_one
from fastinc.state import SegmentArtifact, State, load_state, save_state
from fastinc.synctex import SyncTexError
from fastinc.synctex import merge as merge_synctex
from fastinc.texdist import TexDistribution

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
    """What a build did (``fastinc build --report``): mode, reason, runs, compiled includes."""

    mode: str  # "full", "cold", "incremental" or "noop"
    reason: str | None = None
    runs: list[dict[str, Any]] = field(default_factory=list)
    compiled: list[str] = field(default_factory=list)
    seconds: float = 0.0
    pdf: str | None = None

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
    return _hashes(ctx, names)


def _changed(ctx: Context, files: dict[str, str]) -> list[str]:
    out = []
    for name, digest in files.items():
        path = ctx.analysis.source_dir / name
        if not path.is_file() or _sha(path) != digest:
            out.append(name)
    return out


# --- build steps --------------------------------------------------------------------------------


def _segments(analysis: Analysis) -> list[str]:
    return ["G0"] + [s for k in range(1, len(analysis.includes) + 1) for s in (f"U{k}", f"G{k}")]


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


def _failed_run(ctx: Context, run_dir: Path, err: TexError) -> TexError:
    """Publish the failing run's log (paths mapped) and point the error at it (§6.13)."""
    log = run_dir / f"{ctx.job}.log"
    text = log.read_text(errors="replace") if log.is_file() else ""
    published = publish(
        text_writer(_map(ctx, run_dir, text)),
        ctx.layout.output(".log"),
    )
    err.log = published
    return err


def _map(ctx: Context, run_dir: Path, text: str) -> str:
    mapping = [
        (str(run_dir / RUN_MAIN), str(ctx.analysis.main)),
        *ctx.layout.path_map(),
        (RUN_MAIN, ctx.analysis.main.name),
    ]
    return map_paths(text, mapping)


def _commit_canon(ctx: Context, run_dir: Path) -> None:
    canon = ctx.layout.canon_dir
    if canon.exists():
        shutil.rmtree(canon)
    canon.mkdir(parents=True)
    names = [f"{ctx.job}.aux", *(inc.aux_name for inc in ctx.analysis.includes)]
    names += [f"{ctx.job}{s}" for s in (*DERIVED_SUFFIXES, ".bcf", ".nlo")]
    for name in names:
        src = run_dir / name
        if src.is_file():
            (canon / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, canon / name)


def cold_build(ctx: Context, epoch: int, next_run: int, fmt: FormatInfo) -> State:
    """All units in one run (format + fastinc.sty) to the fixpoint; commit as canonical state."""
    name = f"r{next_run}"
    spec = RunSpec(name, None)
    run_dir = prepare_run_dir(ctx.analysis, ctx.layout, spec, deny_names=ctx.config.state_ignore)
    env = ctx.env(epoch)

    def run_pass() -> PassResult:
        r = run_one(ctx.analysis, ctx.layout, ctx.dist, env, spec, fmt.name)
        return PassResult(r.ok, r.first_error)

    try:
        converge(ctx.job, run_dir, ctx.layout.shadow_dir, ctx.dist, env, run_pass, report=ctx.say)
    except TexError as err:
        if err.first_error is None:  # no fixpoint: plain full mode decides
            raise FallbackError(str(err)) from err
        raise _failed_run(ctx, run_dir, err) from None
    _check_runtime_support(ctx, run_dir, fmt)
    recs = _records(ctx, run_dir)
    _commit_canon(ctx, run_dir)
    seg_files = _segment_files(ctx, recs)
    attributed = {n for files in seg_files.values() for n in files}
    state = State(
        epoch=epoch,
        fingerprints=asdict(ctx.analysis.fingerprints),
        format_stamp=format_stamp(ctx.analysis, ctx.dist.version),
        includes=[inc.arg for inc in ctx.analysis.includes],
        segments={seg: SegmentArtifact(name, _pages(recs, seg)) for seg in _segments(ctx.analysis)},
        segment_files=seg_files,
        global_files=_global_files(ctx, run_dir, attributed),
        next_run=next_run + 1,
    )
    save_state(state, ctx.layout.canon_dir)
    return state


def _records(ctx: Context, run_dir: Path) -> RunRecords:
    try:
        return read_run_records(run_dir, ctx.analysis)
    except RecordError as err:
        raise FallbackError(f"records: {err}") from err


def _pages(recs: RunRecords, seg: str) -> tuple[int, ...]:
    return tuple(p.index for p in recs.pages if p.segment == seg)


def _verify(ctx: Context, run_dir: Path, units: list[int]) -> str | None:
    """None if the compiled units pass on exactly what the canonical state has, else why not."""
    canon = ctx.layout.canon_dir
    new_aux, old_aux = read_lines(run_dir / f"{ctx.job}.aux"), read_lines(canon / f"{ctx.job}.aux")
    new_slices, old_slices = segment_slices(new_aux), segment_slices(old_aux)
    new_levels, old_levels = bookmark_levels(new_aux), bookmark_levels(old_aux)
    nlo_new, nlo_old = run_dir / f"{ctx.job}.nlo", canon / f"{ctx.job}.nlo"
    new_nom = read_nomenclature(nlo_new) if nlo_new.is_file() else {}
    old_nom = read_nomenclature(nlo_old) if nlo_old.is_file() else {}
    for k in units:
        inc = ctx.analysis.includes[k - 1]
        old, new = canon / inc.aux_name, run_dir / inc.aux_name
        if not old.is_file() or not new.is_file():
            return f"{inc.arg}: aux file missing"
        if content_lines(read_lines(old)) != content_lines(read_lines(new)):
            return f"{inc.arg}: aux file changed (labels, lists, state or self data)"
        seg = f"U{k}"
        new_slice = _comparable(new_slices.get(seg, []), new_levels)
        if new_slice != _comparable(old_slices.get(seg, []), old_levels):
            return f"{inc.arg}: entry state, citations, bookmarks or positions changed"
        if new_nom.get(seg, []) != old_nom.get(seg, []):
            return f"{inc.arg}: nomenclature entries changed"
    return None


def _comparable(lines: list[str], levels: dict[int, int]) -> list[str]:
    """Slice lines without structural lines; bookmark entries with their run-local id replaced
    by their level (S6: ids number the entries of a run)."""
    out = []
    for line in content_lines(lines):
        bkm = parse_bookmark(line)
        if bkm is not None:
            line = re.sub(r"\{id=\d+", f"{{level={levels.get(bkm.id)}", line, count=1)
        out.append(line)
    return out


def _dirty_units(ctx: Context, state: State) -> tuple[list[int], str | None]:
    """Include indices (1-based) to compile, grouped by compilation unit, or a cold reason."""
    for seg in _segments(ctx.analysis):
        if seg.startswith("G") and _changed(ctx, state.segment_files.get(seg, {})):
            return (
                [],
                f"glue sources changed ({', '.join(_changed(ctx, state.segment_files[seg]))})",
            )
    index = {inc.arg: k for k, inc in enumerate(ctx.analysis.includes, start=1)}
    dirty: list[int] = []
    for unit in ctx.analysis.units:
        ks = [index[inc.arg] for inc in unit.includes]
        if any(_changed(ctx, state.segment_files.get(f"U{k}", {})) for k in ks):
            dirty += ks
    return dirty, None


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
        return f"global inputs changed ({', '.join(changed[:3])})"
    return None


def incremental_step(ctx: Context, state: State, fmt: FormatInfo) -> tuple[State, list[int]] | str:
    """Compile the dirty units in one run and commit them; returns the new state and compiled
    indices, or a reason for a cold build."""
    dirty, reason = _dirty_units(ctx, state)
    if reason is not None:
        return reason
    if not dirty:
        return state, []
    name = state.new_run_name()
    selection = tuple(ctx.analysis.includes[k - 1].arg for k in dirty)
    spec = RunSpec(name, selection)
    run_dir = prepare_run_dir(
        ctx.analysis,
        ctx.layout,
        spec,
        canon_dir=ctx.layout.canon_dir,
        deny_names=ctx.config.state_ignore,
    )
    ctx.say(f"compiling {', '.join(selection)}")
    r = run_one(ctx.analysis, ctx.layout, ctx.dist, ctx.env(state.epoch), spec, fmt.name)
    if not r.ok:
        raise _failed_run(ctx, run_dir, TexError("pdflatex failed", first_error=r.first_error))
    recs = _records(ctx, run_dir)
    why = _verify(ctx, run_dir, dirty)
    if why is not None:
        return why
    new_files = _segment_files(ctx, recs)
    for k in dirty:
        seg = f"U{k}"
        state.segments[seg] = SegmentArtifact(name, _pages(recs, seg))
        state.segment_files[seg] = new_files.get(seg, {})
    save_state(state, ctx.layout.canon_dir)
    return state, dirty


# --- merge and publish ----------------------------------------------------------------------------


def publish_state(ctx: Context, state: State) -> Path:
    """Merge the canonical segments into the published PDF, SyncTeX file and log."""
    runs: dict[str, RunRecords] = {}
    slices: dict[str, dict[str, list[str]]] = {}

    def records(run: str) -> RunRecords:
        if run not in runs:
            run_dir = ctx.layout.runs_dir / run
            runs[run] = read_run_records(run_dir, ctx.analysis)
            slices[run] = segment_slices(read_lines(run_dir / f"{ctx.job}.aux"))
        return runs[run]

    pages: list[PageSource] = []
    outline: list[OutlineEntry] = []
    syn: list[tuple[Path, int]] = []
    for seg in _segments(ctx.analysis):
        art = state.segments[seg]
        recs = records(art.run)
        run_dir = ctx.layout.runs_dir / art.run
        by_index = {p.index: p for p in recs.pages}
        for i in art.pages:
            pages.append(
                PageSource(run_dir / f"{ctx.job}.pdf", i, by_index[i].value, by_index[i].label)
            )
            syn.append((run_dir / f"{ctx.job}.synctex.gz", i))
        for line in slices[art.run].get(seg, []):
            bkm = parse_bookmark(line)
            if bkm is not None:
                level = recs.bookmark_levels.get(bkm.id, 0)
                outline.append(OutlineEntry(level, bkm.open, bkm.dest, bkm.title))
    first_run = ctx.layout.runs_dir / state.segments["G0"].run
    pdf = publish(
        lambda tmp: _merge_pdf(pages, outline, first_run / f"{ctx.job}.pdf", tmp),
        ctx.layout.output(".pdf"),
    )
    main_name = f"{ctx.analysis.source_dir}/./{ctx.analysis.main.name}"

    def map_path(path: str) -> str:
        if Path(path).name == RUN_MAIN:
            return main_name
        for old, new in ctx.layout.path_map():
            if path.startswith(old + "/"):
                return new + path[len(old) :]
        return path

    try:
        publish(lambda tmp: merge_synctex(syn, map_path, tmp), ctx.layout.output(".synctex.gz"))
    except SyncTexError as err:
        raise FallbackError(f"SyncTeX merge: {err}") from err
    texts = []
    for run in sorted(state.run_names(), key=lambda r: int(r[1:])):
        log = ctx.layout.runs_dir / run / f"{ctx.job}.log"
        texts.append(
            f"%%% fastinc: log of run {run}\n"
            + _map(ctx, log.parent, log.read_text(errors="replace"))
        )
    publish(text_writer("\n".join(texts)), ctx.layout.output(".log"))
    return pdf


def _merge_pdf(
    pages: list[PageSource], outline: list[OutlineEntry], catalog: Path, out: Path
) -> None:
    try:
        merge_pdf(pages, outline, catalog, out)
    except MergeError as err:
        raise FallbackError(f"PDF merge: {err}") from err


def _gc(ctx: Context, state: State) -> None:
    if ctx.config.keep_runs or not ctx.layout.runs_dir.is_dir():
        return
    keep = state.run_names()
    for d in ctx.layout.runs_dir.iterdir():
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d)


# --- entry point -----------------------------------------------------------------------------


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


def build(ctx: Context, epoch: int, *, full: bool = False) -> BuildReport:
    """Build the document: full mode, cold build, incremental step or nothing (§5)."""
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
        if reason is None and state is not None:
            fmt = ensure_format(ctx.analysis, ctx.layout, ctx.dist, ctx.env(state.epoch))
            step = incremental_step(ctx, state, fmt)
            if isinstance(step, tuple):
                state, compiled = step
                pdf = publish_state(ctx, state)
                _gc(ctx, state)
                mode = "incremental" if compiled else "noop"
                runs = (
                    [
                        {
                            "name": f"r{state.next_run - 1}",
                            "selection": [ctx.analysis.includes[k - 1].arg for k in compiled],
                            "passes": 1,
                        }
                    ]
                    if compiled
                    else []
                )
                return BuildReport(
                    mode,
                    None,
                    runs,
                    [ctx.analysis.includes[k - 1].arg for k in compiled],
                    time.monotonic() - start,
                    str(pdf),
                )
            reason = step
        ctx.say(f"cold build: {reason}")
        next_run = state.next_run if state is not None else 1
        try:
            fmt = ensure_format(ctx.analysis, ctx.layout, ctx.dist, ctx.env(epoch))
        except TexError as err:
            raise FallbackError(f"format build failed: {err.first_error}") from err
        state = cold_build(ctx, epoch, next_run, fmt)
        pdf = publish_state(ctx, state)
        _gc(ctx, state)
        return BuildReport(
            "cold",
            reason,
            [{"name": f"r{next_run}", "selection": None}],
            [inc.arg for inc in ctx.analysis.includes],
            time.monotonic() - start,
            str(pdf),
        )
    except FallbackError as fb:
        if fb.persistent:
            canon.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({**stamp_data, "reason": str(fb)}))
        return _full(ctx, epoch, str(fb), start)


def load_epoch(canon_dir: Path, default: int) -> int:
    """SOURCE_DATE_EPOCH of the canonical state (N4), else ``default``."""
    state = load_state(canon_dir)
    return state.epoch if state is not None else default
