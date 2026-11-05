"""TeX distribution adapter (design §6.16). The only module that knows engine flags.

Every TeX, biber and makeindex command line, the TeX environment and the distribution's
path conventions (SyncTeX input paths) come from here. Two implementations: :class:`TeXLive`
and :class:`MiKTeX` (S11: format via ``--undump``, ``--max-print-line``, SyncTeX paths without
``/./``, on-the-fly installation must not prompt).
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Mapping
from functools import cached_property
from pathlib import Path, PureWindowsPath
from typing import Protocol

from chapmk.errors import ToolError
from chapmk.proc import run
from chapmk.texsource import text_lines

#: Directory with chapmk-ini.sty and chapmk.sty; prepended to TEXINPUTS.
TEX_DIR = Path(__file__).resolve().parent / "tex"

REQUIRED_TOOLS = ("pdflatex", "biber", "makeindex", "kpsewhich")
#: TeX files chapmk needs beyond a LaTeX installation (the format build, §6.3)
REQUIRED_FILES = ("mylatexformat.ltx",)


_WINDOWS = os.name == "nt"


def tex_path(path: Path) -> str:
    """Path as passed to TeX: forward slashes on every platform."""
    return path.as_posix()


def deterministic_env(epoch: int) -> dict[str, str]:
    """Variables that make all runs of one build identical (design N4)."""
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
        self, tex_input: str, jobname: str, outdir: Path, fmt: Path | None = None
    ) -> list[str]: ...

    def format_build(self, source: Path, jobname: str, outdir: Path) -> list[str]: ...

    def run_input(self, cwd: Path, run_main: Path) -> str:
        """The command-line input naming ``run_main`` (in a directory on ``TEXINPUTS``) for a
        run with working directory ``cwd``. TeX reads the command line with the catcodes of
        the format, so it must not contain user path characters such as ``_`` (§6.5)."""
        ...

    def biber(self, jobname: str, outdir: Path) -> list[str]: ...

    def makeindex(self, input_name: str, output_name: str, style: str | None) -> list[str]: ...

    def synctex_input(self, cwd: Path, relative: str) -> str:
        """How a run records an input file found relative to its working directory in the
        SyncTeX file (the merge writes the main file in this form)."""
        ...

    def synctex_query(self, cwd: Path, relative: str) -> str:
        """The file name to pass to ``synctex view`` for such a file."""
        ...


class TeXLive:
    """TeX Live on Linux, macOS and Windows."""

    name = "TeX Live"

    def __init__(
        self,
        which: Callable[[str], str | None] = shutil.which,
        find_file: Callable[[str], str] | None = None,
    ) -> None:
        self._which = which
        self._find_file = find_file or _kpsewhich

    def check_tools(self) -> None:
        """Raise :class:`ToolError` listing every required program that is not on PATH, or
        every required TeX file (:data:`REQUIRED_FILES`) that is not installed."""
        missing = [tool for tool in REQUIRED_TOOLS if self._which(tool) is None]
        if missing:
            raise ToolError("required programs not found on PATH: " + ", ".join(missing))
        self._check_files()

    def _check_files(self) -> None:
        missing = [name for name in REQUIRED_FILES if not self._find_file(name)]
        if missing:
            raise ToolError(
                f"required TeX files not found: {', '.join(missing)}; "
                + self._install_hint([Path(m).stem for m in missing])
            )

    def _install_hint(self, packages: list[str]) -> str:
        return f"install them with 'tlmgr install {' '.join(packages)}'"

    @cached_property
    def version(self) -> str:
        """First line of ``pdflatex --version``; part of the format fingerprint."""
        return _banner("pdflatex").strip() or "unknown"

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
        self, tex_input: str, jobname: str, outdir: Path, fmt: Path | None = None
    ) -> list[str]:
        """pdflatex run (§6.5). ``fmt`` is the format file; TeX Live finds it by its *name*
        via ``TEXFORMATS`` (:meth:`environment`): an absolute ``-fmt`` path breaks
        ``-recorder`` (S1)."""
        return [
            "pdflatex",
            *self._format_options(fmt),
            *self._run_options(tex_input, jobname, outdir),
        ]

    def _format_options(self, fmt: Path | None) -> list[str]:
        return [] if fmt is None else [f"-fmt={fmt.stem}"]

    def _run_options(self, tex_input: str, jobname: str, outdir: Path) -> list[str]:
        return [
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-synctex=1",
            "-recorder",
            f"-output-directory={tex_path(outdir)}",
            f"-jobname={jobname}",
            tex_input,
        ]

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
        """biber, run with cwd = source/shadow tree; reads the .bcf from ``outdir`` (§6.10)."""
        return ["biber", "--output-directory", str(outdir), jobname]

    def makeindex(self, input_name: str, output_name: str, style: str | None) -> list[str]:
        """makeindex with relative names (``style`` None: default style); run with cwd =
        output directory (S1)."""
        opts = ["-s", style] if style is not None else []
        return ["makeindex", *opts, "-o", output_name, input_name]

    def run_input(self, cwd: Path, run_main: Path) -> str:
        """The bare file name, found via ``TEXINPUTS`` (§6.5)."""
        return run_main.name

    def synctex_input(self, cwd: Path, relative: str) -> str:
        """``<cwd>/./<relative>``: unresolved, with ``/./`` (S2, S10)."""
        return f"{tex_path(cwd)}/./{relative}"

    def synctex_query(self, cwd: Path, relative: str) -> str:
        """The relative name: ``synctex view`` matches it via the ``/./`` (S10)."""
        return relative


class MiKTeX(TeXLive):
    """MiKTeX (S11). Differences to TeX Live: ``TEXFORMATS`` is ignored, so the format is
    passed as ``--undump=<absolute path>`` (``-recorder`` stays complete); the environment
    variable ``max_print_line`` is ignored, so ``--max-print-line`` is passed; a command-line
    input found via ``TEXINPUTS`` becomes an absolute path, so the run main is given relative to
    the working directory; SyncTeX records
    ``<cwd>/<relative>`` without ``/./``, so ``synctex view`` needs absolute names; on-the-fly
    package installation must not prompt (§6.16)."""

    name = "MiKTeX"

    def __init__(
        self,
        which: Callable[[str], str | None] = shutil.which,
        config_value: Callable[[str], str] | None = None,
        find_file: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__(which, find_file)
        self._config_value = config_value or _initexmf_value

    def check_tools(self) -> None:
        """Required programs, on-the-fly installation set to never (0) or always (1): "ask"
        would prompt or block parallel runs; with "never", the required TeX files must be
        installed (with "always" MiKTeX installs them when the format build reads them)."""
        missing = [t for t in (*REQUIRED_TOOLS, "initexmf") if self._which(t) is None]
        if missing:
            raise ToolError("required programs not found on PATH: " + ", ".join(missing))
        value = self._config_value("[MPM]AutoInstall").strip()
        if value not in ("0", "1"):
            raise ToolError(
                "MiKTeX may ask before installing missing packages "
                f"([MPM]AutoInstall = {value or 'unset'}), which blocks unattended and "
                "parallel runs. Choose 'always' or 'never', e.g. "
                "'initexmf --set-config-value [MPM]AutoInstall=1' "
                "(MiKTeX Console: Settings, 'Always install missing packages on-the-fly')"
            )
        if value == "0":
            self._check_files()

    def _install_hint(self, packages: list[str]) -> str:
        names = " ".join(packages)
        return (
            f"install the MiKTeX package{'s' if len(packages) > 1 else ''} {names} "
            f"(MiKTeX Console: Packages, or 'miktex packages install {names}'), or let MiKTeX "
            "install missing packages on the fly ('initexmf --set-config-value "
            "[MPM]AutoInstall=1')"
        )

    def _format_options(self, fmt: Path | None) -> list[str]:
        return [] if fmt is None else [f"--undump={tex_path(fmt)}"]

    def _run_options(self, tex_input: str, jobname: str, outdir: Path) -> list[str]:
        return ["--max-print-line=10000", *super()._run_options(tex_input, jobname, outdir)]

    def format_build(self, source: Path, jobname: str, outdir: Path) -> list[str]:
        argv = super().format_build(source, jobname, outdir)
        return [argv[0], "--max-print-line=10000", *argv[1:]]

    def run_input(self, cwd: Path, run_main: Path) -> str:
        """The path relative to ``cwd`` (``../runs/r1/chapmk-run.tex``: only chapmk's own
        directory names): MiKTeX replaces a name found via ``TEXINPUTS`` by its absolute path,
        which may contain ``_`` (active with ``underscore``, S11)."""
        return Path(os.path.relpath(run_main, cwd)).as_posix()

    def synctex_input(self, cwd: Path, relative: str) -> str:
        if _WINDOWS:  # native: backslashes, also in the relative part
            return str(PureWindowsPath(cwd.as_posix(), relative))
        return f"{tex_path(cwd)}/{relative}"

    def synctex_query(self, cwd: Path, relative: str) -> str:
        return self.synctex_input(cwd, relative)


def _kpsewhich(name: str) -> str:
    """Path of a TeX file found by ``kpsewhich`` (empty if not installed)."""
    result = run(["kpsewhich", name], cwd=Path.cwd(), env=dict(os.environ))
    lines = [line for line in text_lines(result.output) if line.strip()]
    return lines[-1].strip() if result.ok and lines else ""


def _initexmf_value(name: str) -> str:
    """A MiKTeX configuration value (effective for the current user)."""
    result = run(["initexmf", "--show-config-value", name], cwd=Path.cwd(), env=dict(os.environ))
    lines = [line for line in text_lines(result.output) if line.strip()]
    return lines[-1] if result.ok and lines else ""


def _banner(pdflatex: str) -> str:
    """First line of ``pdflatex --version``."""
    result = run([pdflatex, "--version"], cwd=Path.cwd(), env=dict(os.environ))
    lines = text_lines(result.output)
    return lines[0] if lines else ""


def detect(
    which: Callable[[str], str | None] = shutil.which,
    banner: Callable[[str], str] = _banner,
) -> TexDistribution:
    """The installed distribution, from the version banner of ``pdflatex`` (S11: on Linux
    MiKTeX's ``pdflatex`` is ``/usr/local/bin/pdflatex``, so the path does not tell)."""
    pdflatex = which("pdflatex")
    if pdflatex is None:
        raise ToolError("pdflatex not found on PATH")
    if re.search(r"miktex", pdflatex, re.IGNORECASE) or "MiKTeX" in banner(pdflatex):
        return MiKTeX(which)
    return TeXLive(which)
