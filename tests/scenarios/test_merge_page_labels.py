"""Page labels of the merged PDF (design §6.11).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


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
