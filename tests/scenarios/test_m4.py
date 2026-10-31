"""M4 scenarios (PLAN §8.2): T2-T13, T16, T18, T18b, T19, T20 on the thesis corpus.

Each scenario starts from a built state, edits, builds with ``--check`` (§3.3 against
``--full``) and asserts the compiled includes and runs from ``--report``.

Cross references of the corpus: ch1 -> ch3, ch2 -> ch4, ch3 -> ch5, ch4 -> ch6, ch5 -> ch1,
ch6 -> ch2, appA -> ch3, appB -> ch4 (``\\nameref``, ``\\pageref``, ``\\autoref``).
"""

import time
from pathlib import Path
from typing import Any

import pytest
from _helpers import build, edit, selections

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]

ALL = [f"chapters/ch{k}" for k in range(1, 7)] + ["chapters/appA", "chapters/appB"]
PARA = "\n\n".join(["Additional text to make the chapter longer. " * 40] * 6)


def checked(thesis: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    """Build with --check; assert success and §3.3 equality."""
    rc, rep = build(thesis, "--check", *args)
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "PASS" in out.out, out.out
    return rep


def run_with(rep: dict[str, Any], arg: str) -> dict[str, Any]:
    """The first run of the report that compiled ``arg``."""
    for r in rep["runs"]:
        if r["selection"] is None or arg in r["selection"]:
            return r
    raise AssertionError(f"{arg} not compiled: {selections(rep)}")


def ch(thesis: Path, name: str) -> Path:
    return thesis / "chapters" / f"{name}.tex"


def test_t2_page_count_change_tail_run(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T2: ch3 gets longer -> ch3, then a tail run ch4..appB (entries changed), then the
    importers of moved labels; no full fallback."""
    edit(ch(thesis, "ch3"), "\\section*{Remarks on ch3}", PARA + "\n\\section*{Remarks on ch3}")
    rep = checked(thesis, capsys)
    assert rep["mode"] == "incremental"
    sels = selections(rep)
    assert sels[0] == ["chapters/ch3"]
    tail = run_with(rep, "chapters/ch4")
    assert tail["selection"] is None or set(ALL[3:]) <= set(tail["selection"]), sels
    assert any("entry state changed" in r for r in tail["reasons"]["chapters/ch4"])
    assert set(ALL[2:]) <= set(rep["compiled"])


def test_t3_renamed_section_nameref(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T3: rename a section of ch2 referenced by \\nameref from ch6 -> ch2, ch6 (+glue)."""
    edit(ch(thesis, "ch2"), "\\section{Theory of ch2}", "\\section{Theory of the second chapter}")
    rep = checked(thesis, capsys)
    assert rep["compiled"] == ["chapters/ch2", "chapters/ch6"]
    assert selections(rep)[0] == ["chapters/ch2"]
    assert any(
        "L:sec:ch2-theory" in r for r in run_with(rep, "chapters/ch6")["reasons"]["chapters/ch6"]
    )


def test_t4_new_citation_renumbers(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T4: a new citation in ch4 that sorts first renumbers the bibliography -> ch4, biber,
    all citing units (all chapters cite), glue."""
    edit(
        ch(thesis, "ch4"),
        "Further reading: \\cite{ref20}.",
        "Further reading: \\cite{ref20,ref41}.",
    )
    rep = checked(thesis, capsys)
    runs = rep["runs"]
    assert runs[0]["selection"] == ["chapters/ch4"] and "biber" in runs[0]["tools"]
    assert rep["compiled"] == ALL


def test_t5_new_label_imported(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T5: a new label in ch6 that ch1 references (undefined before) -> ch6, then ch1."""
    edit(ch(thesis, "ch1"), "Further reading:", "Further reading (\\autoref{sec:new6}):")
    rc, rep = build(thesis)
    assert rc == 0 and rep["compiled"] == ["chapters/ch1"]
    edit(ch(thesis, "ch6"), "\\label{sec:ch6-theory}", "\\label{sec:ch6-theory}\\label{sec:new6}")
    rep = checked(thesis, capsys)
    sels = [s for s in selections(rep) if s]
    assert sels == [["chapters/ch6"], ["chapters/ch1"]], selections(rep)
    assert any("L:sec:new6" in r for r in rep["runs"][1]["reasons"]["chapters/ch1"])


def test_t6_new_nomenclature_entry(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T6: a new nomenclature entry in ch2 -> ch2, makeindex, glue (list)."""
    edit(
        ch(thesis, "ch2"),
        "\\nomenclature[B]{$a_{2}$}",
        "\\nomenclature[B]{$z_{2}$}{new symbol of ch2}\\nomenclature[B]{$a_{2}$}",
    )
    rep = checked(thesis, capsys)
    runs = rep["runs"]
    assert runs[0]["selection"] == ["chapters/ch2"] and "makeindex" in runs[0]["tools"]
    assert rep["compiled"] == ["chapters/ch2"]
    assert [] in selections(rep)[1:]  # the glue typesets the nomenclature again


def test_t7_longtable_self_rerun(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T7: a wider longtable cell in ch3 -> ch3 again until its column widths are stable."""
    edit(ch(thesis, "ch3"), "  row 1 &", "  row 1 with a considerably wider first cell &")
    rep = checked(thesis, capsys)
    assert rep["compiled"] == ["chapters/ch3"]
    sels = [s for s in selections(rep) if s]
    assert sels[:2] == [["chapters/ch3"], ["chapters/ch3"]], selections(rep)
    assert any("self data unstable" in r for r in rep["runs"][1]["reasons"]["chapters/ch3"])


def test_t8_algorithm_comment_width(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T8: a wider algorithm comment (eqparbox) in ch4 -> ch4 again (self)."""
    edit(ch(thesis, "ch4"), "\\COMMENT{input}", "\\COMMENT{input tensor and its tolerance}")
    rep = checked(thesis, capsys)
    assert rep["compiled"] == ["chapters/ch4"]
    sels = [s for s in selections(rep) if s]
    assert sels[:2] == [["chapters/ch4"], ["chapters/ch4"]], selections(rep)
    assert any("eqparbox" in r for r in rep["runs"][1]["reasons"]["chapters/ch4"])


def test_t9_new_figure(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T9: a new figure in ch2 -> ch2 and the glue (LoF); later units stay clean."""
    fig = (
        "\\begin{figure}[htb]\n  \\centering\n  \\begin{tikzpicture}\\draw (0,0) rectangle "
        "(1,0.3);\\end{tikzpicture}\n  \\caption{A new small figure}\\label{fig:ch2-new}\n"
        "\\end{figure}\n\n\\section{Tables of ch2}"
    )
    edit(ch(thesis, "ch2"), "\\section{Tables of ch2}", fig)
    rep = checked(thesis, capsys)
    assert rep["compiled"] == ["chapters/ch2"]
    assert [] in selections(rep)[1:]  # list of figures


def test_t10_page_parity_change(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T10: ch1 gets longer (page parity, openright) -> output correct (tail run in M4)."""
    edit(ch(thesis, "ch1"), "\\section*{Remarks on ch1}", PARA + "\n\\section*{Remarks on ch1}")
    rep = checked(thesis, capsys)
    assert rep["mode"] == "incremental" and selections(rep)[0] == ["chapters/ch1"]
    assert set(ALL) == set(rep["compiled"])


def test_t11_moved_appendix(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T11: move \\appendix in main.tex -> all (main body changed)."""
    edit(
        thesis / "main.tex",
        "\\appendix\n\\include{chapters/appA}",
        "\\include{chapters/appA}\n\\appendix",
    )
    rep = checked(thesis, capsys)
    assert rep["mode"] == "cold" and "main file changed" in rep["reason"]
    assert rep["compiled"] == ALL


def _fmt(thesis: Path) -> Path:
    fmts = list((thesis / ".fastinc" / "fmt").glob("*.fmt"))
    assert len(fmts) == 1, fmts
    return fmts[0]


def test_t12a_preamble_after_split(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T12a: preamble edit after the split point -> all units, no format rebuild."""
    before = _fmt(thesis).stat().st_mtime_ns
    edit(
        thesis / "main.tex",
        "\\begin{document}",
        "\\newcommand{\\fastincTestA}{x}\n\\begin{document}",
    )
    rep = checked(thesis, capsys)
    assert rep["mode"] == "cold" and "main file changed" in rep["reason"]
    assert _fmt(thesis).stat().st_mtime_ns == before


def test_t12b_preamble_before_split(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T12b: preamble edit before the split point -> format rebuild, all units."""
    before = _fmt(thesis).stat().st_mtime_ns
    text = (thesis / "main.tex").read_text()
    line = next(x for x in text.split("\n") if x.startswith("\\documentclass"))
    edit(thesis / "main.tex", line, line + "\n\\newcommand{\\fastincTestB}{x}")
    rep = checked(thesis, capsys)
    assert rep["mode"] == "cold" and "format part" in rep["reason"]
    assert _fmt(thesis).stat().st_mtime_ns != before


def test_t13_new_include(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T13: add an \\include -> all."""
    ch(thesis, "ch7").write_text("\\chapter{Extra}\\label{ch:extra}\nSome extra text.\n")
    edit(
        thesis / "main.tex",
        "\\include{chapters/ch6}",
        "\\include{chapters/ch6}\n\\include{chapters/ch7}",
    )
    rep = checked(thesis, capsys)
    assert rep["mode"] == "cold"
    assert rep["compiled"] == [*ALL[:6], "chapters/ch7", *ALL[6:]]


def test_t16_cold_build(
    copy_corpus, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:  # type: ignore[no-untyped-def]
    """T16: cold build equals --full (§3.3); wall times reported."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    src = copy_corpus("thesis")
    t0 = time.monotonic()
    rep = checked(src, capsys)
    cold = rep["seconds"]
    assert rep["mode"] == "cold" and rep["compiled"] == ALL
    t0 = time.monotonic()
    rc, _ = build(src, "--full")
    full = time.monotonic() - t0
    assert rc == 0
    with capsys.disabled():
        print(f"\nT16: cold build {cold:.1f} s ({len(rep['runs'])} runs), --full {full:.1f} s")


def test_t18_setlength_in_unit_body(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T18: \\setlength in the ch2 body -> lint warning; ch2 is global: compiled with all
    later units when it changes, and in every run for its state."""
    edit(
        ch(thesis, "ch2"),
        "\\label{sec:ch2-theory}",
        "\\label{sec:ch2-theory}\n\\setlength{\\parskip}{3pt plus 1pt}",
    )
    rep = checked(thesis, capsys)
    assert any("chapters/ch2.tex:" in w and "\\setlength" in w for w in rep["warnings"])
    assert selections(rep)[0] in (None, ALL[1:])
    # a later edit elsewhere: ch2 is compiled with it (its state reaches later units)
    edit(ch(thesis, "ch4"), "Further reading:", "Furhter reading:")
    rep = checked(thesis, capsys)
    assert selections(rep)[0] == ["chapters/ch2", "chapters/ch4"]


def test_t18b_grouped_setlength(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T18b: \\setlength inside a table environment and inside {...} -> no lint hit."""
    edit(
        ch(thesis, "ch2"),
        "\\begin{table}[htb]\n  \\centering",
        "\\begin{table}[htb]\n  \\centering\\setlength{\\tabcolsep}{4pt}",
    )
    edit(
        ch(thesis, "ch2"),
        "Further reading:",
        "{\\setlength{\\parskip}{0pt}Grouped.} Further reading:",
    )
    rep = checked(thesis, capsys)
    assert rep["warnings"] == []
    assert selections(rep)[0] == ["chapters/ch2"]
    assert "chapters/ch2" in rep["compiled"]


def test_t19_stale_build_files_in_source_dir(
    copy_corpus, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:  # type: ignore[no-untyped-def]
    """T19: stale main.aux, unit aux and list files in the source directory are ignored."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    src = copy_corpus("thesis")
    (src / "main.aux").write_text("\\relax\n\\newlabel{ch:ch1}{{99}{99}{Bogus}{chapter.99}{}}\n")
    (src / "chapters" / "ch1.aux").write_text(
        "\\relax\n\\newlabel{sec:ch1-theory}{{9.9}{9}{X}{x}{}}\n"
    )
    (src / "main.toc").write_text("\\contentsline {chapter}{Bogus}{1}{}%\n")
    (src / "main.bbl").write_text("% stale\n")
    rep = checked(src, capsys)
    assert rep["mode"] == "cold"
    edit(src / "chapters" / "ch3.tex", "Further reading:", "Furhter reading:")
    rep = checked(src, capsys)
    assert rep["compiled"] == ["chapters/ch3"]


def test_t20_split_chapter_is_one_unit(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T20: ch3 split into ch3 (\\chapter) and ch3b (continues with \\section); an edit in
    ch3b compiles the compilation unit {ch3, ch3b}; running heads equal --full (§3.3)."""
    text = ch(thesis, "ch3").read_text()
    cut = text.index("\\section{Figures of ch3}")
    ch(thesis, "ch3").write_text(text[:cut])
    ch(thesis, "ch3b").write_text(text[cut:])
    edit(
        thesis / "main.tex",
        "\\include{chapters/ch3}",
        "\\include{chapters/ch3}\n\\include{chapters/ch3b}",
    )
    rc, rep = build(thesis)
    assert rc == 0 and rep["mode"] == "cold"
    edit(ch(thesis, "ch3b"), "Further reading:", "Furhter reading:")
    rep = checked(thesis, capsys)
    assert rep["compiled"] == ["chapters/ch3", "chapters/ch3b"]
