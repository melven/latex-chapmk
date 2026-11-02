"""Command-line interface (PLAN §6.15): ``build``, ``check``, ``clean``, ``graph``."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import fastinc
from fastinc.analysis import Analysis, analyse
from fastinc.config import Config, load_config
from fastinc.errors import ConfigError, FastincError, TexError
from fastinc.fullbuild import full_build
from fastinc.incremental import Context, build, load_epoch
from fastinc.layout import Layout, make_layout
from fastinc.shadow import sync_project_shadow
from fastinc.texdist import TexDistribution, detect
from fastinc.timing import Timings

#: Marker file proving that a directory is a fastinc build directory (``clean`` safety).
BUILD_DIR_MARKER = ".fastinc-build-dir"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fastinc", description=fastinc.__doc__)
    p.add_argument("--version", action="version", version=f"fastinc {fastinc.__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build the PDF")
    b.add_argument("main", nargs="?", type=Path, help="main .tex file (or 'main' in fastinc.toml)")
    b.add_argument("--full", action="store_true", help="plain full build (reference mode)")
    b.add_argument("-j", "--jobs", type=int, help="parallel pdflatex processes (0 = CPU count)")
    b.add_argument("--build-dir", type=Path, help="build directory (default: .fastinc)")
    b.add_argument("--out-dir", type=Path, help="output directory (default: next to MAIN)")
    b.add_argument("--keep-runs", action="store_true", help="keep run directories")
    b.add_argument(
        "--check",
        action="store_true",
        help="also build with --full and compare (PLAN §3.3); exit 1 on a difference",
    )
    b.add_argument("--report", type=Path, help="write a JSON report of the build to this file")
    b.add_argument("-v", "--verbose", action="store_true")
    k = sub.add_parser("check", help="build, build with --full, compare the results (§3.3)")
    k.add_argument("main", nargs="?", type=Path)
    k.add_argument("--build-dir", type=Path)
    k.add_argument("--out-dir", type=Path)
    k.add_argument("-v", "--verbose", action="store_true")
    c = sub.add_parser("clean", help="remove the build directory")
    c.add_argument("main", nargs="?", type=Path)
    c.add_argument("--build-dir", type=Path)
    g = sub.add_parser("graph", help="compilation units and dependencies of the last build")
    g.add_argument("main", nargs="?", type=Path)
    g.add_argument("--build-dir", type=Path)
    g.add_argument("--format", choices=("text", "dot", "json"), default="text")
    return p


def _say(msg: str) -> None:
    print(f"fastinc: {msg}", file=sys.stderr)


def _prepare(config: Config) -> tuple[Analysis, Layout]:
    analysis = analyse(config)
    for warning in analysis.warnings:
        _say(f"warning: {warning}")
    layout = make_layout(config, analysis)
    layout.build_dir.mkdir(parents=True, exist_ok=True)
    (layout.build_dir / BUILD_DIR_MARKER).touch()
    return analysis, layout


def cmd_build(args: argparse.Namespace, cwd: Path) -> int:
    config = load_config(
        args.main,
        cwd,
        jobs=getattr(args, "jobs", None),
        build_dir=args.build_dir,
        out_dir=args.out_dir,
        keep_runs=getattr(args, "keep_runs", False),
        verbose=args.verbose,
    )
    timings = Timings()
    analysis, layout = _prepare(config)
    dist = detect()
    dist.check_tools()
    timings.lap("analysis")
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", int(time.time())))
    sync_project_shadow(analysis, layout.shadow_dir, layout.build_dir)
    timings.lap("shadow")
    report = _say if config.verbose else (lambda _msg: None)
    ctx = Context(analysis, layout, dist, config, os.environ, report, timings)
    result = build(ctx, epoch, full=getattr(args, "full", False))
    if not config.verbose:
        for warning in result.warnings:
            _say(f"warning: {warning}")
    if config.verbose:
        pass  # the builder reported mode and reasons already
    elif result.mode == "full" and result.reason and result.reason != "--full":
        _say(f"full build: {result.reason}")
    elif result.mode == "cold" and result.reason:
        _say(f"cold build: {result.reason}")
    compiled = f", compiled: {', '.join(result.compiled)}" if result.mode == "incremental" else ""
    _say(f"wrote {result.pdf} ({result.mode}{compiled}, {result.seconds:.1f} s)")
    if getattr(args, "report", None):
        (cwd / args.report).write_text(result.to_json(), encoding="utf-8")
    if args.command == "check" or getattr(args, "check", False):
        return _check(ctx, analysis, layout, dist, epoch)
    return 0


def _check(
    ctx: Context, analysis: Analysis, layout: Layout, dist: TexDistribution, epoch: int
) -> int:
    """Compare the published build with a --full build into <build>/check (same epoch)."""
    from fastinc.check import compare_pdfs, compare_synctex  # pikepdf: only when checking

    ref_layout = replace(layout, out_dir=layout.build_dir / "check")
    ref_epoch = load_epoch(layout.canon_dir, epoch)
    _say("check: building the --full reference")
    full_build(
        analysis,
        ref_layout,
        dist,
        dist.environment(ref_epoch, os.environ),
        report=ctx.say,
        picture_cache=ctx.config.picture_cache,
    )
    ref, got = ref_layout.output(".pdf"), layout.output(".pdf")
    rep = compare_pdfs(ref, got)
    sources = [analysis.main.name] + [f"{inc.arg}.tex" for inc in analysis.includes]
    compare_synctex(ref, got, sources, analysis.source_dir, report=rep)
    print(rep.summary())
    return 0 if rep.ok else 1


def cmd_clean(args: argparse.Namespace, cwd: Path) -> int:
    config = load_config(args.main, cwd, build_dir=args.build_dir)
    layout = make_layout(config, analyse(config))
    if not layout.build_dir.exists():
        return 0
    if not (layout.build_dir / BUILD_DIR_MARKER).is_file():
        raise ConfigError(f"refusing to delete {layout.build_dir}: not a fastinc build directory")
    shutil.rmtree(layout.build_dir)
    _say(f"removed {layout.build_dir}")
    return 0


def cmd_graph(args: argparse.Namespace, cwd: Path) -> int:
    from fastinc.graph import dependency_graph, to_dot, to_json, to_text

    config = load_config(args.main, cwd, build_dir=args.build_dir)
    analysis = analyse(config)
    layout = make_layout(config, analysis)
    try:
        g = dependency_graph(analysis, layout, config)
    except FileNotFoundError as err:
        raise ConfigError(str(err)) from err
    render = {"text": to_text, "dot": to_dot, "json": to_json}[args.format]
    sys.stdout.write(render(g))
    return 0


def main(argv: Sequence[str] | None = None, cwd: Path | None = None) -> int:
    """Run the CLI; returns the exit code (0 ok, 1 TeX error, 2 other errors)."""
    args = _parser().parse_args(argv)
    workdir = cwd or Path.cwd()
    try:
        if args.command in ("build", "check"):
            return cmd_build(args, workdir)
        if args.command == "graph":
            return cmd_graph(args, workdir)
        return cmd_clean(args, workdir)
    except FastincError as err:
        _say(f"error: {err}")
        if isinstance(err, TexError) and err.first_error:
            print(err.first_error, file=sys.stderr)
            if err.log:
                _say(f"see {err.log}")
        return err.exit_code
