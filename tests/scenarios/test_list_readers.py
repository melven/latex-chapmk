"""A unit that typesets a list (a front-matter unit, a class's preface command).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


@pytest.mark.parametrize("front", ["\\tableofcontents\\clearpage", "\\afterpreface"])
def test_table_of_contents_in_a_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], front: str
) -> None:
    """A run that excludes the unit with \\tableofcontents did not open the .toc, so LaTeX
    dropped every unit's entries: the canonical list stayed old and the unit was not
    recompiled after a chapter title changed. Through a macro (mnthesis' \\afterpreface)
    the source scan does not see the list at all: the merged table of contents stayed empty
    (sweep: JinwenFu001/thesis-template). Runs open the document's lists now, and the run's
    \\@starttoc record (L <seg> toc) makes the unit a reader of the list."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\newcommand\\afterpreface{\\tableofcontents\\clearpage}\n"
        "\\begin{document}\n\\include{front}\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "front.tex").write_text(f"Preface.{front}\n")
    (src / "a.tex").write_text("\\chapter{A}Text a.\n\\section{S}\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "\\chapter{B}", "\\chapter{Bee}")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and sorted(rep["compiled"]) == ["b", "front"], rep
