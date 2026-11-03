"""TeX distribution adapter (PLAN §6.16). The only module that knows engine flags.

Every TeX, biber and makeindex command line and the TeX environment come from here, so a
MiKTeX implementation (M7) can be added without touching the driver logic.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Mapping
from functools import cached_property
from pathlib import Path
from typing import Protocol

from chapmk.errors import ToolError
from chapmk.proc import run

#: Directory with chapmk-ini.sty and chapmk.sty; prepended to TEXINPUTS.
TEX_DIR = Path(__file__).resolve().parent / "tex"

REQUIRED_TOOLS = ("pdflatex", "biber", "makeindex", "kpsewhich")


def tex_path(path: Path) -> str:
    """Path as passed to TeX: forward slashes on every platform."""
    return path.as_posix()


def deterministic_env(epoch: int) -> dict[str, str]:
    """Variables that make all runs of one build identical (PLAN N4)."""
    return {"SOURCE_DATE_EPOCH": str(epoch), "FORCE_SOURCE_DATE": "1", "max_print_line": "10000"}


class TexDistribution(Protocol):
    """What the driver needs from a TeX distribution."""

    name: str

    @property
    def version(self) -> str: ...

    def check_tools(self) -> None: ...

    def environment(
        self, epoch: int, base: Mapping[str, str], formats_dir: Path | None = None
    ) -> dict[str, str]: ...

    def pdflatex(
        self, tex_input: str, jobname: str, outdir: Path, fmt: str | None = None
    ) -> list[str]: ...

    def format_build(self, source: Path, jobname: str, outdir: Path) -> list[str]: ...

    def biber(self, jobname: str, outdir: Path) -> list[str]: ...

    def makeindex(self, input_name: str, output_name: str, style: str | None) -> list[str]: ...


class TeXLive:
    """TeX Live on Linux, macOS and Windows."""

    name = "TeX Live"

    def __init__(self, which: Callable[[str], str | None] = shutil.which) -> None:
        self._which = which

    def check_tools(self) -> None:
        """Raise :class:`ToolError` listing every required program that is not on PATH."""
        missing = [tool for tool in REQUIRED_TOOLS if self._which(tool) is None]
        if missing:
            raise ToolError("required programs not found on PATH: " + ", ".join(missing))

    @cached_property
    def version(self) -> str:
        """First line of ``pdflatex --version``; part of the format fingerprint."""
        result = run(["pdflatex", "--version"], cwd=Path.cwd(), env=dict(os.environ))
        return result.output.splitlines()[0].strip() if result.output else "unknown"

    def environment(
        self, epoch: int, base: Mapping[str, str], formats_dir: Path | None = None
    ) -> dict[str, str]:
        """Environment for TeX runs: ``base`` plus N4 variables, chapmk's TeX directory in
        ``TEXINPUTS`` and, for format runs, ``formats_dir`` in ``TEXFORMATS``. A trailing
        path separator keeps kpathsea's default path."""
        env = dict(base)
        env.update(deterministic_env(epoch))
        env["TEXINPUTS"] = f"{TEX_DIR}{os.pathsep}{base.get('TEXINPUTS', '')}"
        if formats_dir is not None:
            env["TEXFORMATS"] = f"{formats_dir}{os.pathsep}{base.get('TEXFORMATS', '')}"
        return env

    def pdflatex(
        self, tex_input: str, jobname: str, outdir: Path, fmt: str | None = None
    ) -> list[str]:
        """pdflatex run (§6.5). ``fmt`` is a format *name* found via ``TEXFORMATS``: an
        absolute ``-fmt`` path breaks ``-recorder`` (S1)."""
        argv = ["pdflatex"]
        if fmt is not None:
            argv.append(f"-fmt={fmt}")
        argv += [
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-synctex=1",
            "-recorder",
            f"-output-directory={tex_path(outdir)}",
            f"-jobname={jobname}",
            tex_input,
        ]
        return argv

    def format_build(self, source: Path, jobname: str, outdir: Path) -> list[str]:
        """mylatexformat format build of ``source`` (§6.3.1)."""
        return [
            "pdflatex",
            "-ini",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-recorder",
            f"-jobname={jobname}",
            f"-output-directory={tex_path(outdir)}",
            "&pdflatex",
            "mylatexformat.ltx",
            tex_path(source),
        ]

    def biber(self, jobname: str, outdir: Path) -> list[str]:
        """biber, run with cwd = source/shadow tree; reads the .bcf from ``outdir`` (P1)."""
        return ["biber", "--output-directory", str(outdir), jobname]

    def makeindex(self, input_name: str, output_name: str, style: str | None) -> list[str]:
        """makeindex with relative names (``style`` None: default style); run with cwd =
        output directory (S1)."""
        opts = ["-s", style] if style is not None else []
        return ["makeindex", *opts, "-o", output_name, input_name]


def detect(which: Callable[[str], str | None] = shutil.which) -> TexDistribution:
    """The installed distribution. MiKTeX is recognised and rejected until M7."""
    pdflatex = which("pdflatex")
    if pdflatex is None:
        raise ToolError("pdflatex not found on PATH")
    if re.search(r"miktex", pdflatex, re.IGNORECASE):
        raise ToolError("MiKTeX is not supported yet (planned for milestone M7)")
    return TeXLive(which)
