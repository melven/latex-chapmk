"""Page labels in chapmk's page records (\\thepage written as plain text).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def test_roman_page_labels_of_babel_spanish(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """babel-spanish typesets roman page numbers with \\es@scroman; chapmk's page records
    wrote \\thepage expanded ("Unbalanced write command" in every run of a document with
    \\frontmatter; plain pdflatex works). The label is written as plain text now."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage[spanish]{babel}\n\\usepackage{hyperref}\n"
        "\\usepackage{bookmark}\n\\begin{document}\n\\frontmatter\n\\tableofcontents\n"
        "\\mainmatter\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Texto a.\n")
    (src / "b.tex").write_text("\\chapter{B}Texto b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Texto b.", "Txeto b.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["b"], rep
