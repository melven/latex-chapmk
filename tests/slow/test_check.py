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


def test_identical_and_different(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    a = build(src, "Same text.", "a")
    b = build(src, "Same text.", "b")
    rep = compare_pdfs(a, b)
    compare_synctex(a, b, [detect().synctex_query(src, "d.tex")], src, report=rep)
    assert rep.ok, rep.summary()
    assert rep.counts["links"] == 1 and rep.counts["outline items"] == 2
    assert rep.counts["synctex records"] > 0 and rep.counts["synctex view"] == 1
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


def test_font_descriptor_metrics_are_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Merged runs can carry other Ascent/CapHeight/Descent/XHeight for a font (pdfTeX takes
    them from one instance of the font; sweep: se-tuebingen, Agda78): not visible, but
    pdftotext's word boxes and, in some layouts (margin notes), its text change. Tolerated
    with a note when the texts agree with the metrics normalised; a real change differs.
    The extraction is simulated: small documents do not show the layout effect."""
    import chapmk.check as check

    src = tmp_path / "s"
    src.mkdir()
    a = build(src, "Same text.", "a")
    b = build(src, "Same text.", "b")
    c = build(src, "Other text.", "c")
    real = check._texts

    def texts(pdf: Path, workdir: Path) -> list[str]:  # b's metrics shift its layout
        pages = real(pdf, workdir)
        return [p + " (layout)" for p in pages] if pdf == b else pages

    monkeypatch.setattr(check, "_texts", texts)
    rep = compare_pdfs(a, b)
    assert rep.ok and rep.counts["text pages"] == 1, rep.summary()
    assert "NOTE text pages: equal up to font descriptor metrics" in rep.summary()
    rep = compare_pdfs(a, c)
    assert "text pages" in {d.item for d in rep.differences} and not rep.notes


def test_widths_rounding_is_tolerated(tmp_path: Path) -> None:
    """pdfTeX rounds a font's /Widths from the size whose font object it created first, which
    depends on the fonts a run used: merged runs can differ by 0.1 per 1000 em, which moves
    later glyphs of a string by antialiased pixels (sweep: LuckeeDev, tintando, wvianna).
    Tolerated with a note; a larger change still differs."""
    import pikepdf

    src = tmp_path / "s"
    src.mkdir()
    body = ("{\\Huge " + "abcdefghijklmnopqrstuvwxyz" * 2 + "}\\par ") * 6
    a = build(src, body, "a")

    def shifted(out: str, delta: float) -> Path:
        pdf = build(src, body, out)
        with pikepdf.open(pdf, allow_overwriting_input=True) as doc:
            for obj in doc.objects:
                if isinstance(obj, pikepdf.Dictionary) and "/Widths" in obj:
                    obj.Widths = pikepdf.Array([float(w) + delta for w in obj.Widths])
            doc.save(pdf)
        return pdf

    b = shifted("b", 0.1)
    rep = compare_pdfs(a, b)
    assert rep.ok and "equal up to /Widths rounding" in rep.summary(), rep.summary()
    rep = compare_pdfs(a, shifted("c", 0.5))
    assert "raster pages" in {d.item for d in rep.differences}, rep.summary()
