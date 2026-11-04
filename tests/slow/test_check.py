"""The §3.3 comparison must accept identical builds and reject different ones."""

from pathlib import Path

import pytest

from chapmk.check import Report, compare_pdfs, compare_synctex
from chapmk.cli import main
from chapmk.texdist import detect

pytestmark = pytest.mark.slow

DOC = """\\documentclass{article}
\\usepackage{hyperref}
\\begin{document}
\\section{One}\\label{s1}
Text with a link to \\ref{s2}.
\\section{Two}\\label{s2}
%s
\\end{document}
"""


def build(src: Path, body: str, out: str) -> Path:
    (src / "d.tex").write_text(DOC % body)
    assert main(["build", "d.tex", "--out-dir", out], cwd=src) == 0
    return src / out / "d.pdf"


def test_identical_and_different(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    src = tmp_path / "s"
    src.mkdir()
    a = build(src, "Same text.", "a")
    b = build(src, "Same text.", "b")
    rep = compare_pdfs(a, b)
    compare_synctex(a, b, [detect().synctex_query(src, "d.tex")], src, report=rep)
    assert rep.ok, rep.summary()
    assert rep.counts["links"] == 1 and rep.counts["outline items"] == 2
    assert rep.counts["synctex view"] >= 3
    c = build(src, "Other text.", "c")
    rep2 = compare_pdfs(a, c)
    assert {d.item for d in rep2.differences} >= {"raster pages", "text pages"}
    assert "FAIL" in rep2.summary()
    # a source without records in the reference compares nothing: a difference, not a pass
    (src / "other.tex").write_text("not\nin\nthe\ndocument\n")
    rep3 = compare_synctex(a, b, [detect().synctex_query(src, "other.tex")], src)
    assert not rep3.ok and "no records" in rep3.summary()


def test_report_compare() -> None:
    r = Report()
    r.compare("x", [1, 2], [1, 2])
    r.compare("y", [1, 2], [1, 3])
    r.compare("z", [1], [1, 2])
    assert [(d.item, d.detail) for d in r.differences] == [
        ("y", "#1: reference 2 != 3"),
        ("z", "length 1 != 2"),
    ]
