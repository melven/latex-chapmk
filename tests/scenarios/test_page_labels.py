"""Page labels: chapmk's page records (\\thepage written as plain text) and the labels of
the merged PDF (design §6.11).

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


@pytest.mark.parametrize("hyperref", [False, True])
def test_roman_front_matter_with_and_without_hyperref(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], hyperref: bool
) -> None:
    """\\frontmatter numbers pages in roman. Only hyperref writes PDF page labels; without it
    a plain build has none (viewers count 1, 2, ...), but the merge wrote /PageLabels from the
    page records (check: page label 'i' instead of '1'; found by the corpus sweep)."""
    src = tmp_path / "src"
    src.mkdir()
    pkgs = "\\usepackage{hyperref}\n\\usepackage{bookmark}\n" if hyperref else ""
    (src / "main.tex").write_text(
        f"\\documentclass{{book}}\n{pkgs}\\begin{{document}}\n\\frontmatter\n\\tableofcontents\n"
        "\\mainmatter\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Text a.\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["b"], rep
