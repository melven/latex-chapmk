"""The first page of the document, typeset right after \\begin{document} (glue before the first
include).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


@pytest.mark.parametrize("preamble", ["", "\\makeatletter\\def\\x@y{}\\makeatother\n"])
def test_vspace_star_right_after_begin_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], preamble: str
) -> None:
    """\\vspace* restores \\prevdepth, so the interline glue of the next line depends on the
    \\prevdepth the preamble left. A format does not dump it: runs started with -1000pt
    ("ignore depth"), the title page lost its 1pt \\lineskip glue and every line below was
    1pt higher (sweep: ary1002, alorenzo175 by 1-4.7pt). With \\makeatother at the end of the
    preamble, the format build did not capture the main vertical list at all (S13; mylatexformat
    reads the preamble with @ a letter; sweep: tscheffl/ThinkC)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        f"\\documentclass{{book}}\n{preamble}\\begin{{document}}\n\\thispagestyle{{empty}}\n"
        "\\vspace*{2.5in}{\\huge Title}\\par\\vspace{1in}{\\Large Author}\\clearpage\n"
        "\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Text a.\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["b"], rep
