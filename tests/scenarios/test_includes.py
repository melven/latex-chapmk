"""Includes (design §6.1): an \\include inside a unit, include arguments as LaTeX accepts
them (\\include{./ch/a}, \\include{ch/a.tex}), an \\include the analysis does not see.

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import build, checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def test_include_in_a_unit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """\\include in a unit's text (\\verb, verbatim: manuals that document \\include) is not a
    nested \\include: the build is incremental. A real nested \\include is LaTeX's error,
    reported with its location."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text(
        "\\chapter{A}Use \\verb|\\include{file}|.\n\\begin{verbatim}\n\\include{x}\n"
        "\\end{verbatim}\n"
    )
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["b"], rep
    (src / "x.tex").write_text("X.\n")
    edit(src / "b.tex", "Txet b.", "\\include{x}")
    rc, _ = build(src)
    err = capsys.readouterr().err
    assert rc == 1 and "b.tex:1: LaTeX Error: \\include cannot be nested" in err, err


def test_include_arguments_with_dot_slash_and_extension(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """\\include{./ch/a} and \\include{ch/b.tex} (LaTeX accepts both): the unit records match
    the includes, and a stale ch/a.aux of a manual build in the source directory stays out
    of the runs (F11). With the name as written, the record check failed (full build) and
    the stale aux file reached the runs (a sweep document stopped with "Unbalanced write")."""
    src = tmp_path / "src"
    (src / "ch").mkdir(parents=True)
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n\\tableofcontents\n"
        "\\include{./ch/a}\n\\include{ch/b.tex}\n\\end{document}\n"
    )
    (src / "ch" / "a.tex").write_text("\\chapter{A}Text a.\n")
    (src / "ch" / "b.tex").write_text("\\chapter{B}Text b.\n")
    (src / "ch" / "a.aux").write_text(
        "\\relax\n\\@writefile{toc}{\\contentsline {chapter}{STALE}{1}{}}\n"
    )
    rep = checked(src, capsys)
    assert rep["mode"] == "cold" and rep["warnings"] == [], rep
    edit(src / "ch" / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["ch/b.tex"], rep
    assert "STALE" not in (src / ".chapmk" / "main" / "canon" / "main.toc").read_text()


def test_include_of_a_subdirectory_file_in_an_input_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """\\include writes fig/ward.aux into the output directory, and TeX does not create
    fig/ there: every build failed ("I can't write on file `fig/ward.aux'"), also the full
    build (sweep: fintelia/thesis). The build directories mirror the source tree's
    subdirectories now; the \\include outside the main file's body still means full mode."""
    src = tmp_path / "src"
    (src / "fig").mkdir(parents=True)
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n\\include{a}\n\\input{design}\n"
        "\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Text a.\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    (src / "design.tex").write_text("\\chapter{Design}Text.\n\\include{fig/ward}\n")
    (src / "fig" / "ward.tex").write_text("A figure.\n")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "fig/ward" in rep["reason"], rep
