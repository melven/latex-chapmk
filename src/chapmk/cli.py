"""Command-line interface (design §6.15): ``build``, ``check``, ``clean``, ``graph``."""

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
from chapmk.errors import ChapmkError, ConfigError, InternalError, TexError, ToolError
from chapmk.files import read_raw
from chapmk.fullbuild import full_build
from chapmk.incremental import Context, build, load_epoch
from chapmk.layout import DEFAULT_BUILD_DIR, Layout, build_dir_of, make_layout
from chapmk.lock import LOCK_FILE, build_lock
from chapmk.logs import map_paths, printed_log
from chapmk.proc import Interrupted, allow_runs, terminate_all
from chapmk.texdist import TexDistribution, detect
from chapmk.timing import Timings
from chapmk.tools import BIBER_OUT

#: Marker file proving that a directory is a chapmk build directory (``clean`` safety).
BUILD_DIR_MARKER = ".chapmk-build-dir"


_NO_WAIT = "fail instead of waiting while another chapmk process uses the build directory"
_DESCRIPTION = """\
latexmk for books: rebuilds only the changed \\include'd chapters of a pdfLaTeX document,
in parallel, and merges them into one PDF and SyncTeX file that look like a full build.
"""
_EPILOG = """\
exit codes:
  0    success (check: no difference)
  1    TeX error (the first error is printed) or check found a difference
  2    other error (configuration, missing program, unsupported document)
  3    internal error (please report it; rerun with -v for the traceback)
  130  interrupted (Ctrl-C), 143 terminated (SIGTERM)

configuration: chapmk.toml next to the main file (see docs/configuration.md)
documentation: https://github.com/melven/latex-chapmk
"""


def _main_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "main", nargs="?", type=Path, help="main .tex file (default: 'main' in chapmk.toml)"
    )
    p.add_argument("--build-dir", type=Path, help="build directory (default: .chapmk/<jobname>)")


def _build_args(p: argparse.ArgumentParser) -> None:
    _main_arg(p)
    p.add_argument("-j", "--jobs", type=int, help="parallel pdflatex processes (0 = CPU count)")
    p.add_argument("--out-dir", type=Path, help="output directory (default: next to MAIN)")
    p.add_argument(
        "--keep-runs", action="store_true", help="keep old run directories (for debugging)"
    )
    p.add_argument("--report", type=Path, help="write a JSON report of the build to this file")
    p.add_argument(
        "--print-log",
        action="store_true",
        help="write the published log to stdout, also after a TeX error (for editors that "
        "parse only the build output, e.g. VS Code LaTeX Workshop)",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", help="print progress, reasons and tracebacks"
    )
    p.add_argument("--no-wait", action="store_true", help=_NO_WAIT)


def _parser() -> argparse.ArgumentParser:
    formatter = argparse.RawDescriptionHelpFormatter
    p = argparse.ArgumentParser(
        prog="chapmk", description=_DESCRIPTION, epilog=_EPILOG, formatter_class=formatter
    )
    p.add_argument("--version", action="version", version=f"chapmk {chapmk.__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")
    b = sub.add_parser(
        "build",
        help="build the PDF (incremental; cold on the first run)",
        description="Build MAIN into MAIN.pdf, MAIN.synctex.gz and MAIN.log next to it.",
        epilog=_EPILOG,
        formatter_class=formatter,
    )
    _build_args(b)
    b.add_argument("--full", action="store_true", help="plain sequential full build, like latexmk")
    b.add_argument(
        "--check",
        action="store_true",
        help="afterwards build with --full and compare (pages, text, links, SyncTeX); "
        "exit 1 on a difference",
    )
    k = sub.add_parser(
        "check",
        help="build, then build with --full and compare the results",
        description="Same as 'build --check': verify that the incremental result equals a\n"
        "plain full build (rendered pages, text, page labels, outline, links, SyncTeX).",
        epilog=_EPILOG,
        formatter_class=formatter,
    )
    _build_args(k)
    c = sub.add_parser("clean", help="remove the build directory")
    _main_arg(c)
    c.add_argument("--no-wait", action="store_true", help=_NO_WAIT)
    g = sub.add_parser("graph", help="compilation units and dependencies of the last build")
    _main_arg(g)
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
    checking = args.command == "check" or getattr(args, "check", False)
    if checking:
        from chapmk.check import check_tools

        check_tools()  # before the build, not after it
    timings.lap("analysis")
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", int(time.time())))
    report = _say if config.verbose else (lambda _msg: None)
    ctx = Context(analysis, layout, dist, config, os.environ, report, timings)
    result = build(ctx, epoch, full=getattr(args, "full", False))
    if not config.verbose:  # verbose: the builder reported all of this already
        for warning in result.warnings:
            _say(f"warning: {warning}")
        for hint in result.hints:
            _say(f"hint: {hint}")
        if result.mode == "cold" and result.reason:
            _say(f"cold build: {result.reason}")
    compiled = f", compiled: {', '.join(result.compiled)}" if result.mode == "incremental" else ""
    _say(f"wrote {result.pdf} ({result.mode}{compiled}, {result.seconds:.1f} s)")
    if getattr(args, "report", None):
        (cwd / args.report).write_text(result.to_json(), encoding="utf-8")
    if getattr(args, "print_log", False):
        _print_log(layout.output(".log"))
        # the state's last biber run (full mode: its own directory), as latexmk prints it
        biber_dir = layout.full_dir if result.mode == "full" else layout.canon_dir
        _print_tool_output(biber_dir / BIBER_OUT, layout.path_map())
    if checking:
        return _check(ctx, analysis, layout, dist, epoch)
    return 0


def _print_log(log: Path) -> None:
    """``--print-log`` (§6.13): the published log on stdout, its bytes unchanged except for the
    repeated banner lines (:func:`printed_log`)."""
    if log.is_file():
        _write_stdout(printed_log(read_raw(log)))


def _print_tool_output(out: Path, mapping: Sequence[tuple[str, str]] = ()) -> None:
    """``--print-log`` (§6.13): a tool's output (biber's: LaTeX Workshop parses its ``INFO``,
    ``WARN`` and ``ERROR`` lines), paths mapped."""
    if out.is_file():
        _write_stdout(map_paths(read_raw(out), mapping))


def _write_stdout(text: str) -> None:
    """``text`` on stdout as UTF-8 with its bytes unchanged (surrogateescape)."""
    data = text.encode("utf-8", "surrogateescape")
    sys.stdout.flush()
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # a text-only stream (e.g. redirected in tests)
        sys.stdout.write(data.decode("utf-8", "replace"))
    else:
        buffer.write(data)
        buffer.flush()


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
    # in the form synctex view matches for this distribution (MiKTeX: absolute, S11; relative
    # names would find nothing on both sides and compare equal)
    names = [analysis.main.name] + [f"{inc.arg}.tex" for inc in analysis.includes]
    sources = [dist.synctex_query(analysis.source_dir, name) for name in names]
    compare_synctex(ref, got, sources, analysis.source_dir, report=rep)
    print(rep.summary())
    return 0 if rep.ok else 1


def cmd_clean(args: argparse.Namespace, cwd: Path) -> int:
    config = load_config(args.main, cwd, build_dir=args.build_dir)
    build_dir = build_dir_of(config)  # no analysis: a broken document can be cleaned (E7)
    if not build_dir.exists():
        return 0
    if not (build_dir / BUILD_DIR_MARKER).is_file():
        raise ConfigError(f"refusing to delete {build_dir}: not a chapmk build directory")
    with build_lock(build_dir, wait=not args.no_wait, say=_say):
        for entry in build_dir.iterdir():  # the open lock file last (Windows)
            if entry.name == LOCK_FILE:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    (build_dir / LOCK_FILE).unlink(missing_ok=True)
    build_dir.rmdir()
    _say(f"removed {build_dir}")
    root = build_dir.parent
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
        if isinstance(err, TexError) and err.log and getattr(args, "print_log", False):
            _print_log(err.log)  # the failing run's log
        if isinstance(err, ToolError) and err.log and getattr(args, "print_log", False):
            _print_tool_output(err.log)  # e.g. the failing biber run's output
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
