"""List files (design §6.7.1): lists of other packages, list writes before the first
include, a list typeset inside a unit (a front-matter unit, a class's preface command).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def test_list_file_with_another_extension(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """C2: \\listofalgorithms of algorithm.sty reads <job>.loa, an extension chapmk did not know.
    It is recorded, stored, spliced and kept fresh; a stale main.loa of a manual build in
    the source directory is not read."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{algorithm}\n\\begin{document}\n"
        "\\listofalgorithms\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    for name, title in (("a", "Alpha"), ("b", "Beta")):
        (src / f"{name}.tex").write_text(
            f"\\chapter{{{name}}}\\begin{{algorithm}}x"
            f"\\caption{{{title} method}}\\end{{algorithm}}\n"
        )
    (src / "main.loa").write_text("\\contentsline {algorithm}{STALE ENTRY}{1}\n")
    assert checked(src, capsys)["mode"] == "cold"
    state = (src / ".chapmk" / "main" / "canon" / "state.json").read_text()
    assert '".loa"' in state
    path = src / "b.tex"
    edit(path, "Beta method", "Gamma method")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental", rep
    loa = (src / ".chapmk" / "main" / "canon" / "main.loa").read_text()
    assert "Gamma method" in loa and "Beta" not in loa and "STALE" not in loa


@pytest.mark.parametrize(
    "before",
    ["\\addtocontents{toc}{\\protect\\relax}", "\\selectlanguage{english}"],
)
def test_list_writes_before_the_first_include(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], before: str
) -> None:
    """S15: a deferred list-file write before the first \\include (\\addtocontents, babel's
    language record) reaches the list files at the first page shipped. A run that compiles
    the first unit ships it after the unit's entry record; the extra first page of a run that
    excludes the unit must too, else the write lands in the unit's list-file section and the
    self-check fails in every build that excludes the unit (full build, then cold)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage[ngerman,english]{babel}\n\\begin{document}\n"
        f"{before}\n\\include{{a}}\n\\include{{b}}\n\\tableofcontents\n\\include{{c}}\n"
        "\\end{document}\n"
    )
    (src / "a.tex").write_text("Title page.\n")
    (src / "b.tex").write_text("Verso.\n")
    (src / "c.tex").write_text("\\chapter{C}Text c.\n")
    rep = checked(src, capsys)
    assert rep["mode"] == "cold" and not any("full build" in w for w in rep["warnings"]), rep
    edit(src / "c.tex", "Text c.", "Txet c.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["c"], rep


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
