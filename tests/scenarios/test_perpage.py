"""Footnotes numbered per page (perpage.sty): full mode.

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def test_footmisc_perpage_builds_in_full_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """footmisc's perpage option loads perpage.sty: counters reset per page through aux data
    and \\c@pabs@page, a macro posing as a counter. Incremental builds failed (unreadable
    records, then wrong page numbers; sweep: BernhardMarconato/computer-vision-exercises),
    so the package is unsupported: full mode with a warning, also after an edit."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage[perpage]{footmisc}\n\\begin{document}\n"
        "\\include{a}\n\\include{b}\n\\include{c}\n\\end{document}\n"
    )
    for name in "abc":
        notes = "".join(f"Text {name}{k}.\\footnote{{Note {name}{k}.}}\n\n" for k in range(40))
        (src / f"{name}.tex").write_text(f"\\chapter{{{name.upper()}}}\n{notes}")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "'perpage'" in rep["reason"], rep
    edit(src / "b.tex", "Text b3.", "Txet b3.")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "'perpage'" in rep["reason"], rep
