"""Full-mode build (PLAN §6.14, F9): plain sequential full runs to a fixpoint, like latexmk.

Used for ``--full``, as the fallback of the incremental driver and as the reference of
``fastinc check``. Runs work in the shadow tree and write into ``<build>/full``; only the final
PDF, SyncTeX file and log are published (path-mapped) to the output directory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from fastinc.analysis import Analysis
from fastinc.errors import TexError, ToolError
from fastinc.gensrc import full_mode_input
from fastinc.layout import Layout
from fastinc.logs import first_error, map_paths
from fastinc.proc import run
from fastinc.publish import copy_bytes, publish
from fastinc.synctex import rewrite_paths
from fastinc.texdist import TexDistribution

MAX_PASSES = 8
NOMENCL_STYLE = "nomencl.ist"

# files that are outputs of a pass, never inputs of the next one
_NOT_INPUTS = (".pdf", ".log", ".fls", ".synctex.gz", ".synctex(busy)", ".blg")


@dataclass(frozen=True)
class FullBuildResult:
    """Published files and statistics of a full-mode build."""

    pdf: Path
    synctex: Path | None
    log: Path
    passes: int
    tool_runs: tuple[str, ...] = field(default=())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(outdir: Path) -> dict[Path, str]:
    """Content hashes of the files in ``outdir`` that a pass may read."""
    return {
        p.resolve(): _digest(p)
        for p in outdir.rglob("*")
        if p.is_file() and not p.name.endswith(_NOT_INPUTS)
    }


def read_inputs(fls: Path, cwd: Path, within: Path) -> set[Path]:
    """Files read by a run (``INPUT`` lines of the ``-recorder`` file) that lie in ``within``."""
    if not fls.is_file():
        return set()
    root = within.resolve()
    found: set[Path] = set()
    for line in fls.read_text(errors="replace").splitlines():
        if line.startswith("INPUT "):
            p = Path(line[6:])
            p = (p if p.is_absolute() else cwd / p).resolve()
            if p.is_relative_to(root) and p.is_file():
                found.add(p)
    return found


@dataclass
class _ToolState:
    """Content hashes of the inputs when biber/makeindex last ran."""

    bcf: str | None = None
    nlo: str | None = None
    runs: list[str] = field(default_factory=list)


def _run_tools(
    analysis: Analysis,
    layout: Layout,
    dist: TexDistribution,
    env: Mapping[str, str],
    state: _ToolState,
) -> None:
    out, job = layout.full_dir, analysis.jobname
    bcf = out / f"{job}.bcf"
    if bcf.is_file() and _digest(bcf) != state.bcf:
        r = run(dist.biber(job, out), cwd=layout.shadow_dir, env=env, log_path=out / "biber.out")
        if not r.ok:
            raise ToolError(f"biber failed, see {out / f'{job}.blg'}")
        state.bcf = _digest(bcf)
        state.runs.append("biber")
    nlo = out / f"{job}.nlo"
    if nlo.is_file() and _digest(nlo) != state.nlo:
        argv = dist.makeindex(nlo.name, f"{job}.nls", NOMENCL_STYLE)
        r = run(argv, cwd=out, env=env, log_path=out / "makeindex.out")
        if not r.ok:
            raise ToolError(f"makeindex failed: {r.output.strip()[-500:]}")
        state.nlo = _digest(nlo)
        state.runs.append("makeindex")


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
) -> FullBuildResult:
    """Run pdflatex (plus biber and makeindex for nomencl) until no file read by a pass
    changed during that pass, then publish the results.

    On a TeX error the previous published PDF is kept, the failing log is published and a
    :class:`TexError` is raised. The shadow tree must be up to date.
    """
    out, job = layout.full_dir, analysis.jobname
    out.mkdir(parents=True, exist_ok=True)
    for inc in analysis.includes:  # \include writes <arg>.aux into the output directory (S2)
        (out / inc.aux_name).parent.mkdir(parents=True, exist_ok=True)
    argv = dist.pdflatex(full_mode_input(analysis), job, out)
    tools = _ToolState()
    for n in range(1, max_passes + 1):
        before = _snapshot(out)
        result = run(argv, cwd=layout.shadow_dir, env=env)
        log = out / f"{job}.log"
        if not result.ok or not (out / f"{job}.pdf").is_file():
            _publish_log(analysis, layout)
            text = log.read_text(errors="replace") if log.is_file() else result.output
            err = first_error(map_paths(text, layout.path_map()))
            raise TexError(
                f"pdflatex failed in pass {n}", log=layout.output(".log"), first_error=err
            )
        _run_tools(analysis, layout, dist, env, tools)
        changed = sorted(
            p.name
            for p in read_inputs(out / f"{job}.fls", layout.shadow_dir, out)
            if before.get(p) != _digest(p)
        )
        report(f"pass {n}: " + (f"changed {', '.join(changed)}" if changed else "stable"))
        if not changed:
            break
    else:
        raise TexError(
            f"no fixpoint after {max_passes} passes (files keep changing)", log=out / f"{job}.log"
        )

    pdf = publish(copy_bytes(out / f"{job}.pdf"), layout.output(".pdf"))
    syn_src = out / f"{job}.synctex.gz"
    syn: Path | None = None
    if syn_src.is_file():
        syn = publish(
            lambda tmp: rewrite_paths(syn_src, tmp, layout.path_map()), layout.output(".synctex.gz")
        )
    return FullBuildResult(pdf, syn, _publish_log(analysis, layout), n, tuple(tools.runs))
