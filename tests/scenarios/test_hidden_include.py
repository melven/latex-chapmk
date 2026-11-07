"""An \\include the analysis does not see (in an \\input file), of a file in a subdirectory.

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


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
