"""Command-line interface (PLAN §6.15). M1: ``build`` (full mode) and ``clean``."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import fastinc
from fastinc.analysis import Analysis, analyse
from fastinc.config import Config, load_config
from fastinc.errors import ConfigError, FastincError, TexError
from fastinc.fullbuild import full_build
from fastinc.layout import Layout, make_layout
from fastinc.shadow import sync_project_shadow
from fastinc.texdist import detect

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
    b.add_argument("-v", "--verbose", action="store_true")
    c = sub.add_parser("clean", help="remove the build directory")
    c.add_argument("main", nargs="?", type=Path)
    c.add_argument("--build-dir", type=Path)
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
        jobs=args.jobs,
        build_dir=args.build_dir,
        out_dir=args.out_dir,
        keep_runs=args.keep_runs,
        verbose=args.verbose,
    )
    start = time.monotonic()
    analysis, layout = _prepare(config)
    dist = detect()
    dist.check_tools()
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", int(time.time())))
    env = dist.environment(epoch, os.environ)
    sync_project_shadow(analysis, layout.shadow_dir, layout.build_dir)
    if not args.full:
        reasons = list(analysis.fallback_reasons) or ["incremental builds are not implemented yet"]
        for reason in reasons:
            _say(f"full build: {reason}")
    report = _say if config.verbose else (lambda _msg: None)
    result = full_build(analysis, layout, dist, env, report=report)
    _say(f"wrote {result.pdf} ({result.passes} passes, {time.monotonic() - start:.1f} s)")
    return 0


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


def main(argv: Sequence[str] | None = None, cwd: Path | None = None) -> int:
    """Run the CLI; returns the exit code (0 ok, 1 TeX error, 2 other errors)."""
    args = _parser().parse_args(argv)
    workdir = cwd or Path.cwd()
    try:
        if args.command == "build":
            return cmd_build(args, workdir)
        return cmd_clean(args, workdir)
    except FastincError as err:
        _say(f"error: {err}")
        if isinstance(err, TexError) and err.first_error:
            print(err.first_error, file=sys.stderr)
            if err.log:
                _say(f"see {err.log}")
        return err.exit_code
