"""Incremental runs (PLAN §6.5): run directory preparation and a parallel process pool."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from chapmk.analysis import Analysis
from chapmk.files import write_if_changed
from chapmk.gensrc import run_main
from chapmk.layout import Layout
from chapmk.logs import first_error, map_paths
from chapmk.proc import run, terminate_all
from chapmk.texdist import TexDistribution

#: File name of the generated run main. TeX reads the command line with the catcodes of the
#: format, where e.g. the ``underscore`` package makes ``_`` active; so the command line holds
#: only this fixed name and the file is found via ``TEXINPUTS`` (run directory first).
RUN_MAIN = "chapmk-run.tex"

#: List files LaTeX writes for the usual lists; further ones are recorded at runtime (``L``
#: records of ``\\@starttoc``) and kept in the state.
DEFAULT_LIST_SUFFIXES = (".toc", ".lof", ".lot", ".loalg", ".lol", ".tdo")
#: Derived files written by the tools (biber, makeindex for nomencl).
TOOL_SUFFIXES = (".bbl", ".nls")
#: Derived files of a document with the default lists.
DERIVED_SUFFIXES = (*DEFAULT_LIST_SUFFIXES, *TOOL_SUFFIXES)


def derived_suffixes(list_suffixes: Sequence[str]) -> tuple[str, ...]:
    """Derived files copied from the canonical state into a run directory (read by the glue):
    the list files plus the tool outputs."""
    return (*list_suffixes, *TOOL_SUFFIXES)


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
    fmt_name: str,
) -> RunResult:
    """Run pdflatex with the format in a prepared run directory (cwd = shadow tree).
    ``env`` must contain the format directory in ``TEXFORMATS``."""
    run_dir = layout.runs_dir / spec.name
    job = analysis.jobname
    run_env = dict(env)
    run_env["TEXINPUTS"] = f"{run_dir}{os.pathsep}{env.get('TEXINPUTS', '')}"
    argv = dist.pdflatex(RUN_MAIN, job, run_dir, fmt=fmt_name)
    result = run(argv, cwd=layout.shadow_dir, env=run_env, log_path=run_dir / "pdflatex.out")
    log = run_dir / f"{job}.log"
    # a run without pages (glue-only run of a document whose glue ships none) writes no PDF
    no_pages = log.is_file() and "No pages of output." in log.read_text(errors="replace")
    ok = result.ok and ((run_dir / f"{job}.pdf").is_file() or no_pages)
    err = None
    if not ok:
        text = log.read_text(errors="replace") if log.is_file() else result.output
        mapping = [
            (str(run_dir / RUN_MAIN), str(analysis.main)),
            *layout.path_map(),
            (RUN_MAIN, analysis.main.name),
        ]
        err = first_error(map_paths(text, mapping))
    return RunResult(spec, run_dir, ok, result.seconds, err, log)


def run_batch(
    analysis: Analysis,
    layout: Layout,
    dist: TexDistribution,
    env: Mapping[str, str],
    specs: Sequence[RunSpec],
    fmt_name: str,
    jobs: int,
) -> list[RunResult]:
    """Run prepared runs with at most ``jobs`` parallel pdflatex processes (N2). Results are
    returned in the order of ``specs``. Threads only wait for subprocesses (no fork)."""
    pool = ThreadPoolExecutor(max_workers=max(1, jobs))
    try:
        futures = [
            pool.submit(run_one, analysis, layout, dist, env, spec, fmt_name) for spec in specs
        ]
        return [f.result() for f in futures]
    except BaseException:  # a signal in the main thread: stop the workers' processes (C8)
        terminate_all()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
