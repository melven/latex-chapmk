"""M3 scenarios (PLAN §8.2): T1, T14, T15, T17 on the thesis corpus; unit grouping on hgb.
The M3 test of the cold fallback after a layout change is replaced by T2 (M4).

Each scenario asserts §3.3 equality against --full (``chapmk build --check``) and the set of
compiled includes from ``--report``.
"""

from pathlib import Path

import pytest
from _helpers import EPOCH, build, edit, selections

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def test_t1_typo_compiles_one_unit(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T1 (+T15, T17 via --check): typo in ch3 -> only ch3, output equals --full.

    Right after a run with all units, one glue-only run can follow: a deferred write of the
    glue (``\\appendix`` writes ``\\def\\@chapapp`` into the list files at the next
    shipout) lands after appB's entries instead of before them when appA is not compiled,
    so the list files change once (PLAN §6.7.1). In the steady state a typo is one run.
    """
    # the cold build ended with a run of all units: its .bcf is a full run's
    bcf = thesis / ".chapmk" / "canon" / "main.bcf"
    full_bcf = bcf.read_bytes()
    # typo in body text after the \\todo (whose margin-note position is recorded)
    edit(thesis / "chapters" / "ch3.tex", "Further reading:", "Furhter reading:")
    rc, rep = build(thesis, "--check")
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert rep["mode"] == "incremental", rep
    assert rep["compiled"] == ["chapters/ch3"]
    runs = rep["runs"]
    assert runs[0]["selection"] == ["chapters/ch3"]
    assert [(r["selection"], r["glue"]) for r in runs[1:]] in (
        [],
        [([], "glue inputs changed (lists)")],
    ), runs
    assert "PASS" in out.out and "synctex view" in out.out
    # §6.10: the .bcf patched from a partial run is byte-identical to the full run's
    assert bcf.read_bytes() == full_bcf
    # steady state: a second typo is exactly one run, no glue-only run
    edit(thesis / "chapters" / "ch3.tex", "Furhter reading:", "Further readin:")
    rc, rep = build(thesis, "--check")
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert selections(rep) == [["chapters/ch3"]]
    # nothing to do afterwards: the published files are not even rewritten
    pdf = thesis / "main.pdf"
    stamp = pdf.stat().st_mtime_ns
    rc, rep = build(thesis)
    assert (rc, rep["mode"], rep["compiled"]) == (0, "noop", [])
    assert pdf.stat().st_mtime_ns == stamp and "merge_pdf" not in rep["timings"]
    # ... unless something else wrote them (e.g. latexmk in the same directory)
    pdf.write_bytes(b"overwritten")
    rc, rep = build(thesis)
    assert (rc, rep["mode"]) == (0, "noop") and pdf.read_bytes()[:5] == b"%PDF-"


def test_t14_syntax_error_keeps_previous_pdf(
    thesis: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = (thesis / "main.pdf").read_bytes()
    lines = (thesis / "chapters" / "ch4.tex").read_text().split("\n")
    lines.insert(4, "\\undefinedmacro")
    (thesis / "chapters" / "ch4.tex").write_text("\n".join(lines))
    capsys.readouterr()
    rc, _ = build(thesis)
    err = capsys.readouterr().err
    assert rc == 1
    assert "chapters/ch4.tex:5: Undefined control sequence" in err
    assert (thesis / "main.pdf").read_bytes() == pdf
    assert "Undefined control sequence" in (thesis / "main.log").read_text()
    # removing the error restores the canonical sources: nothing to compile, output correct
    lines.pop(4)
    (thesis / "chapters" / "ch4.tex").write_text("\n".join(lines))
    rc, rep = build(thesis, "--check")
    assert rc == 0 and rep["mode"] == "noop" and rep["compiled"] == []


def test_compilation_unit_grouping_hgb(
    copy_corpus,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = copy_corpus("hgb")
    assert build(src)[0] == 0
    edit(src / "chapters" / "usage_details.tex", "param_7 & m", "param_7 & mm")
    rc, rep = build(src, "--check")
    out = capsys.readouterr()
    assert rc == 0, out.out
    assert rep["mode"] == "incremental"
    assert rep["compiled"] == ["chapters/usage", "chapters/usage_details"]
