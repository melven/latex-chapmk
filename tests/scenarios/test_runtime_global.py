"""A unit that switches page numbering or page style through a macro the lint does not see.

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


@pytest.mark.parametrize(
    "switch", ["\\pagenumbering{arabic}", "\\pagestyle{headings}"], ids=["numbering", "style"]
)
def test_page_numbering_switched_in_a_class_macro(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], switch: str
) -> None:
    """tcdthesis switches to arabic page numbers and the text page style in \\@chapter for
    chapter 1: inside the first unit, hidden from the lint. Runs that excluded that unit kept
    roman numbers for later units (sweep: AprilS21/Dissertation, page label vi instead of 6).
    The run records the change (G <unit> <command>) and the unit becomes global."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n"
        f"\\newcommand\\firstchapter{{{switch}\\chapter}}\n"
        "\\begin{document}\n\\pagenumbering{roman}\\pagestyle{plain}Front matter.\\clearpage\n"
        "\\include{a}\n\\include{b}\n\\include{c}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\firstchapter{A}Text a.\\clearpage More a.\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\\clearpage More b.\n")
    (src / "c.tex").write_text("\\chapter{C}Text c.\\clearpage More c.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "c.tex", "Text c.", "Txet c.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["a", "c"], rep
