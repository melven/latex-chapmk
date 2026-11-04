"""Assumptions of the LaTeX packages about TeX Live and package internals, tested directly
(the scenario tests only show their failure as a page difference somewhere)."""

import os
import subprocess
from pathlib import Path

import pytest

from chapmk.texdist import TEX_DIR

pytestmark = pytest.mark.slow

# pgf <= 3.1.11 (TeX Live <= 2025) loads tikz libraries with `\input file\relax', which runs
# no LaTeX file hooks; pgf 3.1.12 uses \InputIfFileExists
OLD_PGF_LOADER = (
    "\\def\\pgfutil@InputIfFileExists#1#2#3{\\pgfutil@IfFileExists{#1}{\\input #1\\relax#2}{#3}}"
)


@pytest.mark.parametrize("loader", ["current", "pgf<=3.1.11"])
def test_externalize_is_redirected_once(tmp_path: Path, loader: str) -> None:
    """chapmk-ini.sty replaces externalize's system call by its picture handler right after
    the external library is loaded, whichever way pgf loads it, and only once (a second
    redirection would make \\tikzexternalize call itself)."""
    emulate = OLD_PGF_LOADER if loader != "current" else ""
    (tmp_path / "main.tex").write_text(
        "\\RequirePackage{chapmk-ini}\n\\documentclass{article}\n\\usepackage{tikz}\n"
        f"\\makeatletter{emulate}\\makeatother\n"
        "\\usetikzlibrary{external}\n\\usetikzlibrary{calc}\n\\makeatletter\n"
        "\\typeout{REDIRECTED=\\ifx\\tikzexternal@externalizefig@systemcall@@\\chapmk@picture"
        " yes\\else no\\fi}\n"
        "\\typeout{LOOP=\\ifx\\chapmk@orig@externalize\\tikzexternalize yes\\else no\\fi}\n"
        "\\makeatother\n\\begin{document}x\\end{document}\n"
    )
    env = dict(os.environ, TEXINPUTS=f"{TEX_DIR}{os.pathsep}")
    subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "main.tex"],
        cwd=tmp_path,
        env=env,
        check=False,
        stdout=subprocess.DEVNULL,
    )
    log = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    assert "REDIRECTED=yes" in log
    assert "LOOP=no" in log
