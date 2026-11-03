"""Full-mode build (PLAN §6.14, F9): plain sequential full runs to a fixpoint, like latexmk.

Used for ``--full``, as the fallback of the incremental driver and as the reference of
``chapmk check``. Tests cache these references by source hash in ``.test-cache/``: after
an intended change of the output, ``rm -rf .test-cache``. Runs work in the shadow tree and
write into ``<build>/full``; only the final PDF, SyncTeX file and log are published
(path-mapped) to the output directory.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from chapmk.analysis import Analysis
from chapmk.aux import read_lines
from chapmk.deps import cite_values, label_values, short_hash
from chapmk.errors import TexError, ToolError
from chapmk.fmt import format_stamp, internal_dirs
from chapmk.gensrc import full_mode_input
from chapmk.layout import Layout
from chapmk.logs import first_error, map_paths
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
from chapmk.proc import run
from chapmk.publish import copy_bytes, publish
from chapmk.shadow import external_inputs, read_inputs, stat_signatures
from chapmk.synctex import rewrite_paths
from chapmk.texdist import TexDistribution

MAX_PASSES = 8
NOMENCL_STYLE = "nomencl.ist"

# files that are outputs of a pass, never inputs of the next one
_NOT_INPUTS = (".pdf", ".log", ".fls", ".synctex.gz", ".synctex(busy)", ".blg", PICS_FILE)


@dataclass(frozen=True)
class FullBuildResult:
    """Published files and statistics of a full-mode build."""

    pdf: Path
    synctex: Path | None
    log: Path
    passes: int
    tool_runs: tuple[str, ...] = field(default=())


def _names(names: list[str], limit: int = 5) -> str:
    """``a, b, c, ... (+12 more)`` for progress messages."""
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown}, ... (+{len(names) - limit} more)"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(outdir: Path) -> dict[Path, str]:
    """Content hashes of the files in ``outdir`` that a pass may read."""
    return {
        Path(p).absolute(): _digest(p)
        for p in outdir.rglob("*")
        if p.is_file() and not p.name.endswith(_NOT_INPUTS)
    }


@dataclass
class ToolState:
    """Content hashes of the inputs when biber/makeindex last ran, and the tool runs."""

    bcf: str | None = None
    nlo: str | None = None
    idx: str | None = None
    runs: list[str] = field(default_factory=list)


def run_tools(
    job: str,
    outdir: Path,
    cwd: Path,
    dist: TexDistribution,
    env: Mapping[str, str],
    state: ToolState,
) -> None:
    """Run biber, makeindex for nomencl (``.nlo``) and makeindex for a generic index
    (``.idx``, default style, like latexmk) in ``outdir`` when their inputs changed."""
    bcf = outdir / f"{job}.bcf"
    if bcf.is_file() and _digest(bcf) != state.bcf:
        r = run(dist.biber(job, outdir), cwd=cwd, env=env, log_path=outdir / "biber.out")
        if not r.ok:
            raise ToolError(f"biber failed, see {outdir / f'{job}.blg'}")
        state.bcf = _digest(bcf)
        state.runs.append("biber")
    nlo = outdir / f"{job}.nlo"
    if nlo.is_file() and _digest(nlo) != state.nlo:
        argv = dist.makeindex(nlo.name, f"{job}.nls", NOMENCL_STYLE)
        r = run(argv, cwd=outdir, env=env, log_path=outdir / "makeindex.out")
        if not r.ok:
            raise ToolError(f"makeindex failed: {r.output.strip()[-500:]}")
        state.nlo = _digest(nlo)
        state.runs.append("makeindex")
    idx = outdir / f"{job}.idx"
    if idx.is_file() and _digest(idx) != state.idx:
        r = run(
            dist.makeindex(idx.name, f"{job}.ind", None),
            cwd=outdir,
            env=env,
            log_path=outdir / "makeindex-idx.out",
        )
        if not r.ok:
            raise ToolError(f"makeindex failed: {r.output.strip()[-500:]}")
        state.idx = _digest(idx)
        state.runs.append("makeindex (index)")


@dataclass(frozen=True)
class PassResult:
    """Outcome of one pdflatex pass for :func:`converge`."""

    ok: bool
    first_error: str | None
    rerun: str | None = None  # a reason for another pass besides changed files


def converge(
    job: str,
    outdir: Path,
    cwd: Path,
    dist: TexDistribution,
    env: Mapping[str, str],
    run_pass: Callable[[], PassResult],
    *,
    report: Callable[[str], None] = lambda _msg: None,
    max_passes: int = MAX_PASSES,
) -> tuple[int, ToolState]:
    """Repeat ``run_pass`` (plus biber/makeindex) until no build file read by a pass changed
    during it (latexmk's criterion). Returns the number of passes and the tool runs.

    Raises :class:`TexError` (``log`` = the run's log) on a failing pass or without fixpoint.
    """
    tools = ToolState()
    log = outdir / f"{job}.log"
    for n in range(1, max_passes + 1):
        before = _snapshot(outdir)
        result = run_pass()
        if not result.ok:
            raise TexError(f"pdflatex failed in pass {n}", log=log, first_error=result.first_error)
        run_tools(job, outdir, cwd, dist, env, tools)
        changed = sorted(
            p.name
            for p in read_inputs(outdir / f"{job}.fls", cwd, outdir)
            if not p.name.endswith(_NOT_INPUTS) and before.get(p) != _digest(p)
        )
        why = [f"changed {_names(changed)}"] if changed else []
        if result.rerun is not None:
            why.append(result.rerun)
        report(f"pass {n}: " + ("; ".join(why) if why else "stable"))
        if not why:
            return n, tools
    raise TexError(f"no fixpoint after {max_passes} passes (files keep changing)", log=log)


def _publish_log(analysis: Analysis, layout: Layout) -> Path:
    log = layout.full_dir / f"{analysis.jobname}.log"
    text = map_paths(log.read_text(errors="replace"), layout.path_map()) if log.is_file() else ""

    def write(tmp: Path) -> None:
        tmp.write_text(text, encoding="utf-8")

    return publish(write, layout.output(".log"))


def full_build(
    analysis: Analysis,
    layout: Layout,
    dist: TexDistribution,
    env: Mapping[str, str],
    *,
    report: Callable[[str], None] = lambda _msg: None,
    max_passes: int = MAX_PASSES,
    picture_cache: bool = True,
    fig_dir: Path | None = None,
) -> FullBuildResult:
    """Full mode: pdflatex on the unmodified sources (with chapmk-ini) to a fixpoint, then
    publish the results.

    With the user's TikZ externalize, pictures are exported into ``fig_dir`` (default
    ``layout.full_fig_dir``) and embedded in a further pass (§6.17), so the result equals an
    externalized build.

    On a TeX error the previous published PDF is kept, the failing log is published and a
    :class:`TexError` is raised. The shadow tree must be up to date.
    """
    out, job = layout.full_dir, analysis.jobname
    out.mkdir(parents=True, exist_ok=True)
    for inc in analysis.includes:  # \include writes <arg>.aux into the output directory (S2)
        (out / inc.aux_name).parent.mkdir(parents=True, exist_ok=True)
    argv = dist.pdflatex(full_mode_input(analysis), job, out)
    fig_dir = (fig_dir or layout.full_fig_dir) if picture_cache else None
    # format stamp: distribution, chapmk-ini.sty, chapmk.sty, driver version, preamble
    stamp = short_hash(
        format_stamp(analysis, dist.version)
        + json.dumps(asdict(analysis.fingerprints), sort_keys=True)
    )

    def run_pass() -> PassResult:
        # key part for references in pictures: all label and citation values of the last pass
        auxes = sorted(out.rglob("*.aux"))
        values = label_values(read_lines(p) for p in auxes)
        values.update(cite_values(out / f"{job}.bbl"))
        refs = short_hash(json.dumps(sorted(values.items())))
        if fig_dir is not None:  # package updates; files (tables, inputs, images) changed
            check_inputs(fig_dir)
            remove_figures(fig_dir, stale_figures(fig_dir, None, analysis.source_dir))
        text = driver_file(fig_dir, layout.shadow_dir, stamp, {"-": refs})
        (out / PICS_FILE).write_text(text, encoding="utf-8")
        result = run(argv, cwd=layout.shadow_dir, env=env)
        if result.ok and (out / f"{job}.pdf").is_file():
            pictures = read_pictures(out / f"{job}.log")
            exported = 0
            if fig_dir is not None:
                exported = export_figures(out / f"{job}.pdf", pictures, fig_dir)
                for p in pictures:
                    if p.exported:
                        store_references(fig_dir, p, {}, analysis.source_dir)
                if exported:
                    fls = out / f"{job}.fls"
                    dist_files = external_inputs(fls, layout.shadow_dir, internal_dirs(layout))
                    record_inputs(fig_dir, stat_signatures(dist_files))
                collect_garbage(fig_dir, {p.key for p in pictures})
            return PassResult(True, None, f"{exported} pictures exported" if exported else None)
        log = out / f"{job}.log"
        text = log.read_text(errors="replace") if log.is_file() else result.output
        return PassResult(False, first_error(map_paths(text, layout.path_map())))

    try:
        passes, tools = converge(
            job, out, layout.shadow_dir, dist, env, run_pass, report=report, max_passes=max_passes
        )
    except TexError as err:
        err.log = _publish_log(analysis, layout)
        raise

    pdf = publish(copy_bytes(out / f"{job}.pdf"), layout.output(".pdf"))
    syn_src = out / f"{job}.synctex.gz"
    syn: Path | None = None
    if syn_src.is_file():
        syn = publish(
            lambda tmp: rewrite_paths(syn_src, tmp, layout.path_map()), layout.output(".synctex.gz")
        )
    return FullBuildResult(pdf, syn, _publish_log(analysis, layout), passes, tuple(tools.runs))
