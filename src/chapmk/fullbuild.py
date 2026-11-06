"""Full-mode build (design §6.14, F9): plain sequential full runs to a fixpoint, like latexmk.

Used for ``--full``, as the fallback of the incremental driver and as the reference of
``chapmk check``. Tests cache these references by source hash in ``.test-cache/``: after
an intended change of the output, ``rm -rf .test-cache``. Runs work in the shadow tree and
write into ``<build>/full``; only the final PDF, SyncTeX file and log are published
(path-mapped) to the output directory.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from chapmk.analysis import Analysis
from chapmk.auxfile import read_lines
from chapmk.deps import cite_values, label_values, short_hash
from chapmk.errors import TexError
from chapmk.files import digest, read_log, write_atomic
from chapmk.fmt import format_stamp
from chapmk.gensrc import full_mode_input
from chapmk.layout import Layout
from chapmk.logs import map_paths, run_error, short_list
from chapmk.pictures import (
    PICS_FILE,
    collect_garbage,
    driver_file,
    export_run,
    picture_stamp,
    read_pictures,
    record_inputs,
    refresh_cache,
)
from chapmk.proc import run
from chapmk.publish import copy_bytes, publish, publish_all, text_writer
from chapmk.recorder import dist_signatures, read_inputs
from chapmk.synctex import rewrite_paths
from chapmk.texdist import TexDistribution
from chapmk.tools import NOMENCL_STYLE, run_biber, run_makeindex

MAX_PASSES = 8
#: present in the full-mode directory while passes run (C7): a kill leaves it, and the next
#: full build starts from an empty directory
JOURNAL_FILE = ".in-progress"

# files that are outputs of a pass, never inputs of the next one
_NOT_INPUTS = (
    ".pdf",
    ".log",
    ".fls",
    ".synctex.gz",
    ".synctex(busy)",
    ".blg",
    PICS_FILE,
    JOURNAL_FILE,
)


@dataclass(frozen=True)
class FullBuildResult:
    """Published files and statistics of a full-mode build."""

    pdf: Path
    synctex: Path | None
    log: Path
    passes: int
    tool_runs: tuple[str, ...] = field(default=())


def _snapshot(outdir: Path) -> dict[Path, str]:
    """Content hashes of the files in ``outdir`` that a pass may read."""
    return {
        Path(p).absolute(): digest(p)
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
    if bcf.is_file() and digest(bcf) != state.bcf:
        run_biber(dist, job, outdir, cwd, env)
        state.bcf = digest(bcf)
        state.runs.append("biber")
    nlo = outdir / f"{job}.nlo"
    if nlo.is_file() and digest(nlo) != state.nlo:
        run_makeindex(dist, nlo.name, f"{job}.nls", NOMENCL_STYLE, outdir, env)
        state.nlo = digest(nlo)
        state.runs.append("makeindex")
    idx = outdir / f"{job}.idx"
    if idx.is_file() and digest(idx) != state.idx:
        run_makeindex(dist, idx.name, f"{job}.ind", None, outdir, env, "makeindex-idx.out")
        state.idx = digest(idx)
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
            if not p.name.endswith(_NOT_INPUTS) and before.get(p) != digest(p)
        )
        why = [f"changed {short_list(changed, 5)}"] if changed else []
        if result.rerun is not None:
            why.append(result.rerun)
        report(f"pass {n}: " + ("; ".join(why) if why else "stable"))
        if not why:
            return n, tools
    raise TexError(f"no fixpoint after {max_passes} passes (files keep changing)", log=log)


def _publish_log(analysis: Analysis, layout: Layout) -> Path:
    log = layout.full_dir / f"{analysis.jobname}.log"
    text = map_paths(read_log(log), layout.path_map()) if log.is_file() else ""
    return publish(text_writer(text), layout.output(".log"))


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
    journal = out / JOURNAL_FILE
    if journal.exists():  # a pass was killed: its aux files may be truncated (C7)
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    write_atomic(journal, "")
    for inc in analysis.includes:  # \include writes <arg>.aux into the output directory (S2)
        (out / inc.aux_name).parent.mkdir(parents=True, exist_ok=True)
    argv = dist.pdflatex(full_mode_input(analysis), job, out)
    fig_dir = (fig_dir or layout.full_fig_dir) if picture_cache else None
    stamp = picture_stamp(format_stamp(analysis, dist.version), asdict(analysis.fingerprints))

    def run_pass() -> PassResult:
        # key part for references in pictures: all label and citation values of the last pass
        auxes = sorted(out.rglob("*.aux"))
        values = label_values(read_lines(p) for p in auxes)
        values.update(cite_values(out / f"{job}.bbl"))
        refs = short_hash(json.dumps(sorted(values.items())))
        if fig_dir is not None:  # package updates; files (tables, inputs, images) changed
            refresh_cache(fig_dir, None, analysis.source_dir)
        text = driver_file(fig_dir, layout.shadow_dir, stamp, {"-": refs})
        (out / PICS_FILE).write_text(text, encoding="utf-8")
        result = run(argv, cwd=layout.shadow_dir, env=env)
        if result.ok and (out / f"{job}.pdf").is_file():
            pictures = read_pictures(out / f"{job}.log")
            exported = 0
            if fig_dir is not None:
                pdf = out / f"{job}.pdf"
                exported = export_run(fig_dir, pdf, pictures, {}, analysis.source_dir)
                if exported:
                    fls = out / f"{job}.fls"
                    record_inputs(
                        fig_dir, dist_signatures(fls, layout.shadow_dir, layout.internal_dirs)
                    )
                collect_garbage(fig_dir, {p.key for p in pictures})
            return PassResult(True, None, f"{exported} pictures exported" if exported else None)
        return PassResult(False, run_error(out / f"{job}.log", result.output, layout.path_map()))

    try:
        passes, tools = converge(
            job, out, layout.shadow_dir, dist, env, run_pass, report=report, max_passes=max_passes
        )
    except TexError as err:  # TeX ended normally: its files are complete
        journal.unlink()
        err.log = _publish_log(analysis, layout)
        raise
    journal.unlink()

    # PDF and SyncTeX as one step, SyncTeX first (C16, as the incremental builder)
    syn_src = out / f"{job}.synctex.gz"
    items: list[tuple[Callable[[Path], None], Path]] = []
    if syn_src.is_file():
        items.append(
            (
                lambda tmp: rewrite_paths(syn_src, tmp, layout.path_map()),
                layout.output(".synctex.gz"),
            )
        )
    items.append((copy_bytes(out / f"{job}.pdf"), layout.output(".pdf")))
    *syn, pdf = publish_all(items)
    return FullBuildResult(
        pdf, syn[0] if syn else None, _publish_log(analysis, layout), passes, tuple(tools.runs)
    )
