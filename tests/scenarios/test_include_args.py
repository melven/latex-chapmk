"""Include arguments as LaTeX accepts them (\\include{./ch/a}, \\include{ch/a.tex}).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


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
