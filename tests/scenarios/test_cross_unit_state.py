"""State that crosses unit boundaries (design §6.4.2, §6.8.4): running heads, primitive
marks, anchors used by later segments (S19), page colour and switches left open at a
unit's end (S18), page numbering or page style switched at run time.

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit, reasons, selections

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def _heads_document(src: Path, extra: str = "") -> None:
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{lipsum}\n\\begin{document}\n\\tableofcontents\n"
        "\\include{a}\n\\include{b}\n\\include{c}\n\\end{document}\n"
    )
    for x in "abc":  # a ends on page 5: blank page 6 before b (head of a's last section)
        n = 9 if x == "a" else 3
        (src / f"{x}.tex").write_text(
            f"\\chapter{{Chap {x}}}\n\\section{{Sec {x} one}}\n\\lipsum*[1-4]\n"
            f"\\section{{Sec {x} two}}\nText {x}.{extra if x == 'a' else ''}\n\\lipsum*[1-{n}]\n"
        )


def test_running_heads_of_excluded_units(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """book, openright: the blank page before a chapter shows the running head of the last
    section of the previous chapter. An excluded unit restores the marks its committing run
    recorded at its end; the marks are part of the state vector, so a changed last heading
    recompiles the following unit (entry state changed)."""
    src = tmp_path / "src"
    _heads_document(src)
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "b.tex"
    edit(path, "Text b.", "Txet b.")
    rep = checked(src, capsys)
    assert selections(rep) == [["b"]], rep["runs"]
    path = src / "a.tex"
    edit(path, "Sec a two", "Sec a TWO")
    rep = checked(src, capsys)
    b = reasons(rep, "b")
    assert any(x.startswith("entry state changed (marks 2e-right") for x in b), rep["runs"]


def test_primitive_marks_fall_back(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A primitive \\mark cannot be restored for excluded units: full mode with a warning."""
    src = tmp_path / "src"
    _heads_document(src, "\\mark{raw}")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "primitive marks" in rep["reason"], rep
    assert any("primitive marks" in w for w in rep["warnings"]), rep
    # persistent (full-only.json): the next build skips the attempt, still with the warning
    runs = src / ".chapmk" / "main" / "runs"
    before = sorted(p.name for p in runs.iterdir())
    rep = checked(src, capsys)
    assert sorted(p.name for p in runs.iterdir()) == before  # no incremental run
    assert rep["mode"] == "full" and [r["name"] for r in rep["runs"]] == ["full"], rep
    assert any("primitive marks" in w for w in rep["warnings"]), rep
    assert (src / ".chapmk" / "main" / "canon" / "full-only.json").is_file()


def _anchor_document(src: Path, cls: str, after: str, start: str = "") -> None:
    """Three units with sections and a figure; ``after``: main-file text after the last
    include; ``start``: the start of units b and c (default: a numbered chapter)."""
    src.mkdir()
    (src / "main.tex").write_text(
        f"\\documentclass[listof=totoc]{{{cls}}}\n\\usepackage{{lipsum}}\n"
        "\\usepackage{hyperref}\n\\usepackage{bookmark}\n\\begin{document}\n\\tableofcontents\n"
        f"\\include{{a}}\n\\include{{b}}\n\\include{{c}}\n{after}\n\\end{{document}}\n"
    )
    for x in "abc":
        head = start if start and x != "a" else f"\\chapter{{Chap {x}}}"
        (src / f"{x}.tex").write_text(
            f"{head}\n\\section{{First of {x}}}\nText {x}.\n\\lipsum[1-3]\n"
            f"\\begin{{figure}}[h]\\rule{{2cm}}{{1cm}}\\caption{{Fig {x}}}\\end{{figure}}\n"
            f"\\section{{Last of {x}}}\n\\lipsum[4-6]\n"
        )


def test_anchor_of_the_last_unit_used_after_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S19 (sweep C1): after the last \\include, KOMA's listof=totoc and a manual
    \\addcontentsline link to the last anchor of c (KOMA's \\chapter* sets none), \\label takes
    c's last number, also in a plain build. A run without c would use an older anchor: c is
    compiled in every run, with a warning and the fix. With \\phantomsection after the page
    break the main file has its own anchor: no warning, typos compile one unit."""
    src = tmp_path / "src"
    _anchor_document(
        src,
        "scrbook",
        "\\listoffigures\n\\cleardoublepage\n\\addcontentsline{toc}{chapter}{REFERENCES}"
        "\\label{refs}\nREFERENCES (\\ref{refs}, \\nameref{refs}).",
    )
    rep = checked(src, capsys)
    for line in ("main.tex:10: \\addcontentsline", "main.tex:12: \\addcontentsline"):
        assert any(
            w.startswith(line) and "c is compiled in every run" in w for w in rep["warnings"]
        )
    assert any(w.startswith("main.tex:12: \\label") for w in rep["warnings"]), rep["warnings"]
    edit(src / "a.tex", "Text a.", "Txet a.")
    assert selections(checked(src, capsys)) == [["a", "c"]]
    edit(
        src / "main.tex",
        "\\listoffigures\n\\cleardoublepage\n",
        "\\cleardoublepage\\phantomsection\n\\listoffigures\n\\cleardoublepage\\phantomsection\n",
    )
    edit(
        src / "main.tex", "\\label{refs}\nREFERENCES (\\ref{refs}, \\nameref{refs}).", "REFERENCES."
    )
    rep = checked(src, capsys)
    assert rep["mode"] == "cold" and not any("anchor" in w for w in rep["warnings"]), rep
    edit(src / "b.tex", "Text b.", "Txet b.")
    assert selections(checked(src, capsys)) == [["b"]]


def test_anchor_used_at_the_start_of_a_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S19: KOMA's \\chapter* sets no anchor, so an \\addcontentsline right after it at the
    start of b links to a's last anchor: a is compiled in every run. Sections renumbered after
    \\chapter* reuse a's anchor names; those are b's own. With \\phantomsection after
    \\chapter* (an edit of b only), a is a normal unit again."""
    src = tmp_path / "src"
    _anchor_document(src, "scrbook", "", "\\chapter*{Star}\\addcontentsline{toc}{chapter}{Star}")
    rep = checked(src, capsys)
    lines = sorted(
        w.split(":")[0] + ":" + w.split(":")[1] for w in rep["warnings"] if "anchor" in w
    )
    assert lines == ["b.tex:1", "c.tex:1"], rep["warnings"]
    edit(src / "c.tex", "Text c.", "Txet c.")
    assert selections(checked(src, capsys)) == [None]  # a and b are global: all units
    for x in "bc":
        edit(src / f"{x}.tex", "\\chapter*{Star}", "\\chapter*{Star}\\phantomsection")
    rep = checked(src, capsys)
    assert not any("anchor" in w for w in rep["warnings"]), rep["warnings"]
    edit(src / "c.tex", "Txet c.", "Text c.")
    assert selections(checked(src, capsys)) == [["c"]]


def test_contents_line_before_the_bibliography(
    thesis: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S19 (sweep C1): \\addcontentsline{toc}{chapter}{...} before \\printbibliography links
    to the last anchor of appB: appB is compiled in every run."""
    edit(
        thesis / "main.tex",
        "\\printbibliography\n",
        "\\cleardoublepage\n\\addcontentsline{toc}{chapter}{REFERENCES}\n\\printbibliography\n",
    )
    rep = checked(thesis, capsys)
    assert any("chapters/appB is compiled in every run" in w for w in rep["warnings"]), rep
    edit(thesis / "chapters" / "ch5.tex", "Further reading:", "Furhter reading:")
    rep = checked(thesis, capsys)
    assert selections(rep)[0] == ["chapters/ch5", "chapters/appB"], rep["runs"]


def test_page_colour_set_in_a_unit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """S18: \\pagecolor sets the page colour globally; a run that excludes the unit that set
    it gave later pages the default colour. The lint makes the unit global."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{xcolor}\n\\begin{document}\n"
        "\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Text a.\n\\pagecolor{yellow}\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)  # files are attributed (and linted) after the first run
    assert rep["mode"] == "incremental" and rep["compiled"] == ["a", "b"], rep
    assert any("a.tex:2: \\pagecolor" in w for w in rep["warnings"]), rep


@pytest.mark.parametrize(
    "switch",
    [
        "\\color{red}",
        "\\pdfrender{TextRenderingMode=Invisible}",
        "\\bfseries",
        "\\small",
        "\\raggedright",
        "\\linespread{1.6}\\selectfont",
    ],
)
def test_state_left_open_at_the_end_of_a_unit(
    copy_corpus,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
    switch: str,
) -> None:
    """S18: a state switch at the top level of a unit stays in effect for the next units; a
    run that excludes the unit started them in the default state (wrong output). The lint
    warns and makes the unit global: it is compiled with the later units."""
    src = copy_corpus("minimal/S18-unit-state")
    edit(src / "a.tex", "% end of a", switch)
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)  # files are attributed (and linted) after the first run
    assert rep["mode"] == "incremental" and rep["compiled"] == ["a", "b"], rep
    assert any("a.tex:3:" in w and "stays in effect" in w for w in rep["warnings"]), rep


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
