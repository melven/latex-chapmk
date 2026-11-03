"""Command-line interface (PLAN §6.15): ``build``, ``check``, ``clean``, ``graph``."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import threading
import time
import traceback
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import chapmk
from chapmk.analysis import Analysis, analyse
from chapmk.config import Config, load_config
from chapmk.errors import ChapmkError, ConfigError, InternalError, TexError
from chapmk.fullbuild import full_build
from chapmk.incremental import Context, build, load_epoch
from chapmk.layout import DEFAULT_BUILD_DIR, Layout, make_layout
from chapmk.lock import LOCK_FILE, build_lock
from chapmk.proc import Interrupted, allow_runs, terminate_all
from chapmk.shadow import sync_project_shadow
from chapmk.state import load_state
from chapmk.texdist import TexDistribution, detect
from chapmk.timing import Timings

#: Marker file proving that a directory is a chapmk build directory (``clean`` safety).
BUILD_DIR_MARKER = ".chapmk-build-dir"


_NO_WAIT = "fail instead of waiting while another chapmk process uses the build directory"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chapmk", description=chapmk.__doc__)
    p.add_argument("--version", action="version", version=f"chapmk {chapmk.__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build the PDF")
    b.add_argument("main", nargs="?", type=Path, help="main .tex file (or 'main' in chapmk.toml)")
    b.add_argument("--full", action="store_true", help="plain full build (reference mode)")
    b.add_argument("-j", "--jobs", type=int, help="parallel pdflatex processes (0 = CPU count)")
    b.add_argument("--build-dir", type=Path, help="build directory (default: .chapmk/<jobname>)")
    b.add_argument("--out-dir", type=Path, help="output directory (default: next to MAIN)")
    b.add_argument("--keep-runs", action="store_true", help="keep run directories")
    b.add_argument(
        "--check",
        action="store_true",
        help="also build with --full and compare (PLAN §3.3); exit 1 on a difference",
    )
    b.add_argument("--report", type=Path, help="write a JSON report of the build to this file")
    b.add_argument("-v", "--verbose", action="store_true")
    b.add_argument("--no-wait", action="store_true", help=_NO_WAIT)
    k = sub.add_parser("check", help="build, build with --full, compare the results (§3.3)")
    k.add_argument("main", nargs="?", type=Path)
    k.add_argument("--build-dir", type=Path)
    k.add_argument("--out-dir", type=Path)
    k.add_argument("-v", "--verbose", action="store_true")
    k.add_argument("--no-wait", action="store_true", help=_NO_WAIT)
    c = sub.add_parser("clean", help="remove the build directory")
    c.add_argument("main", nargs="?", type=Path)
    c.add_argument("--build-dir", type=Path)
    c.add_argument("--no-wait", action="store_true", help=_NO_WAIT)
    g = sub.add_parser("graph", help="compilation units and dependencies of the last build")
    g.add_argument("main", nargs="?", type=Path)
    g.add_argument("--build-dir", type=Path)
    g.add_argument("--format", choices=("text", "dot", "json"), default="text")
    return p


def _say(msg: str) -> None:
    print(f"chapmk: {msg}", file=sys.stderr)


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
    with build_lock(layout.build_dir, wait=not args.no_wait, say=_say):
        return _build_locked(args, cwd, config, timings, analysis, layout)


def _build_locked(
    args: argparse.Namespace,
    cwd: Path,
    config: Config,
    timings: Timings,
    analysis: Analysis,
    layout: Layout,
) -> int:
    dist = detect()
    dist.check_tools()
    timings.lap("analysis")
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", int(time.time())))
    state = load_state(layout.canon_dir)  # list files found earlier: excluded too
    suffixes = state.list_suffixes if state is not None else ()
    sync_project_shadow(analysis, layout.shadow_dir, layout.build_dir, suffixes)
    timings.lap("shadow")
    report = _say if config.verbose else (lambda _msg: None)
    ctx = Context(analysis, layout, dist, config, os.environ, report, timings)
    result = build(ctx, epoch, full=getattr(args, "full", False))
    if not config.verbose:
        for warning in result.warnings:
            _say(f"warning: {warning}")
        for hint in result.hints:
            _say(f"hint: {hint}")
    if config.verbose:
        pass  # the builder reported mode and reasons already
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
    from chapmk.check import compare_pdfs, compare_synctex  # pikepdf: only when checking

    ref_layout = replace(layout, out_dir=layout.build_dir / "check")
    ref_epoch = load_epoch(layout.canon_dir, epoch)
    _say("check: building the --full reference")
    # a fresh picture cache: the reference is a fresh externalized build, so a stale figure of
    # a persistent cache cannot be on both sides
    fresh_figs = layout.build_dir / "check-fig"
    shutil.rmtree(fresh_figs, ignore_errors=True)
    full_build(
        analysis,
        ref_layout,
        dist,
        dist.environment(ref_epoch, os.environ),
        report=ctx.say,
        picture_cache=ctx.config.picture_cache,
        fig_dir=fresh_figs,
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
        raise ConfigError(f"refusing to delete {layout.build_dir}: not a chapmk build directory")
    with build_lock(layout.build_dir, wait=not args.no_wait, say=_say):
        for entry in layout.build_dir.iterdir():  # the open lock file last (Windows)
            if entry.name == LOCK_FILE:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    (layout.build_dir / LOCK_FILE).unlink(missing_ok=True)
    layout.build_dir.rmdir()
    _say(f"removed {layout.build_dir}")
    root = layout.build_dir.parent
    if root.name == DEFAULT_BUILD_DIR and not any(root.iterdir()):
        root.rmdir()  # the default build root holds no other job
    return 0


def cmd_graph(args: argparse.Namespace, cwd: Path) -> int:
    from chapmk.graph import dependency_graph, to_dot, to_json, to_text

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


class _Terminated(BaseException):
    """SIGTERM (e.g. an editor stopping a build on the next save)."""


def _on_sigterm(_signum: int, _frame: object) -> None:
    raise _Terminated


def main(argv: Sequence[str] | None = None, cwd: Path | None = None) -> int:
    """Run the CLI; returns the exit code: 0 ok, 1 TeX error, 2 other errors, 3 internal error
    (C9), 130/143 after SIGINT/SIGTERM (all child processes are killed first, C8)."""
    args = _parser().parse_args(argv)
    workdir = cwd or Path.cwd()
    main_thread = threading.current_thread() is threading.main_thread()
    previous = signal.signal(signal.SIGTERM, _on_sigterm) if main_thread else None
    try:
        return _main(args, workdir)
    except (KeyboardInterrupt, _Terminated, Interrupted) as err:
        terminate_all()
        _say("interrupted")
        return 143 if isinstance(err, _Terminated) else 130
    finally:
        allow_runs()
        if main_thread:
            signal.signal(signal.SIGTERM, previous)


def _main(args: argparse.Namespace, workdir: Path) -> int:
    try:
        if args.command in ("build", "check"):
            return cmd_build(args, workdir)
        if args.command == "graph":
            return cmd_graph(args, workdir)
        return cmd_clean(args, workdir)
    except ChapmkError as err:
        _say(f"error: {err}")
        if isinstance(err, TexError) and err.first_error:
            print(err.first_error, file=sys.stderr)
            if err.log:
                _say(f"see {err.log}")
        return err.exit_code
    except Exception as err:  # a bug: no traceback unless -v (C9)
        if getattr(args, "verbose", False):
            traceback.print_exc()
        hint = "" if getattr(args, "verbose", False) else "; rerun with -v for the traceback"
        _say(f"internal error: {type(err).__name__}: {err} (please report it{hint})")
        return InternalError.exit_code
