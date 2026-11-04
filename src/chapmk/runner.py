"""Incremental runs (design §6.5): run directory preparation and a parallel process pool."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from chapmk.analysis import Analysis
from chapmk.facts import DEFAULT_LIST_SUFFIXES, derived_suffixes
from chapmk.files import read_log, write_if_changed
from chapmk.gensrc import run_main
from chapmk.layout import Layout
from chapmk.logs import map_paths, run_error
from chapmk.proc import run, terminate_all
from chapmk.texdist import TexDistribution

#: File name of the generated run main. TeX reads the command line with the catcodes of the
#: format, where e.g. the ``underscore`` package makes ``_`` active; so the command line holds
#: only this fixed name and the file is found via ``TEXINPUTS`` (run directory first).
RUN_MAIN = "chapmk-run.tex"


@dataclass(frozen=True)
class RunSpec:
    """One pdflatex run: a unique ``name`` (run directory) and the selected includes
    (``None`` = all, ``()`` = glue only)."""

    name: str
    selection: tuple[str, ...] | None


@dataclass(frozen=True)
class RunResult:
    """Outcome of a run. ``first_error`` is path-mapped; ``log`` is the run's log file."""

    spec: RunSpec
    directory: Path
    ok: bool
    seconds: float
    first_error: str | None
    log: Path


def run_path_map(analysis: Analysis, layout: Layout, run_dir: Path) -> list[tuple[str, str]]:
    """Substitutions from a run's paths to the user's (§6.13): the run main (absolute, relative
    to the shadow tree as MiKTeX gets it, bare name) to the main file, the shadow tree to the
    source directory."""
    main = run_dir / RUN_MAIN
    return [
        (str(main), str(analysis.main)),
        (Path(os.path.relpath(main, layout.shadow_dir)).as_posix(), str(analysis.main)),
        *layout.path_map(),
        (RUN_MAIN, analysis.main.name),
    ]


def map_run_paths(analysis: Analysis, layout: Layout, run_dir: Path, text: str) -> str:
    """``text`` (a run's log or messages) with the run's paths mapped to the user's."""
    return map_paths(text, run_path_map(analysis, layout, run_dir))


def prepare_run_dir(
    analysis: Analysis,
    layout: Layout,
    spec: RunSpec,
    *,
    canon_dir: Path | None = None,
    deny_names: Sequence[str] = (),
    list_suffixes: Sequence[str] = DEFAULT_LIST_SUFFIXES,
) -> Path:
    """Create an empty run directory with the canonical aux files, derived files, include
    subdirectories (S2) and the generated run main :data:`RUN_MAIN` (§6.2)."""
    run_dir = layout.runs_dir / spec.name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    job = analysis.jobname
    names = [f"{job}.aux", *(inc.aux_name for inc in analysis.includes)]
    names += [f"{job}{suffix}" for suffix in derived_suffixes(list_suffixes)]
    for inc in analysis.includes:
        (run_dir / inc.aux_name).parent.mkdir(parents=True, exist_ok=True)
    if canon_dir is not None:
        for name in names:
            src = canon_dir / name
            if src.is_file():
                shutil.copyfile(src, run_dir / name)
    write_if_changed(
        run_dir / RUN_MAIN, run_main(analysis, spec.selection, deny_names, list_suffixes)
    )
    return run_dir


def run_one(
    analysis: Analysis,
    layout: Layout,
    dist: TexDistribution,
    env: Mapping[str, str],
    spec: RunSpec,
    fmt: Path,
) -> RunResult:
    """Run pdflatex with the format file ``fmt`` in a prepared run directory (cwd = shadow
    tree). ``env`` comes from :meth:`TexDistribution.environment` with the format directory."""
    run_dir = layout.runs_dir / spec.name
    job = analysis.jobname
    run_env = dict(env)
    run_env["TEXINPUTS"] = f"{run_dir}{os.pathsep}{env.get('TEXINPUTS', '')}"
    argv = dist.pdflatex(
        dist.run_input(layout.shadow_dir, run_dir / RUN_MAIN), job, run_dir, fmt=fmt
    )
    result = run(argv, cwd=layout.shadow_dir, env=run_env, log_path=run_dir / "pdflatex.out")
    log = run_dir / f"{job}.log"
    # a run without pages (glue-only run of a document whose glue ships none) writes no PDF
    no_pages = log.is_file() and "No pages of output." in read_log(log)
    ok = result.ok and ((run_dir / f"{job}.pdf").is_file() or no_pages)
    err = None
    if not ok:
        err = run_error(log, result.output, run_path_map(analysis, layout, run_dir))
    return RunResult(spec, run_dir, ok, result.seconds, err, log)


def run_batch(
    analysis: Analysis,
    layout: Layout,
    dist: TexDistribution,
    env: Mapping[str, str],
    specs: Sequence[RunSpec],
    fmt: Path,
    jobs: int,
) -> list[RunResult]:
    """Run prepared runs with at most ``jobs`` parallel pdflatex processes (N2). Results are
    returned in the order of ``specs``. Threads only wait for subprocesses (no fork)."""
    pool = ThreadPoolExecutor(max_workers=max(1, jobs))
    try:
        futures = [pool.submit(run_one, analysis, layout, dist, env, spec, fmt) for spec in specs]
        return [f.result() for f in futures]
    except BaseException:  # a signal in the main thread: stop the workers' processes (C8)
        terminate_all()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
