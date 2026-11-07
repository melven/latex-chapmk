"""check.box_metrics_copy without TeX: the normalisation of font descriptor metrics."""

from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name

from chapmk.check import box_metrics_copy


def test_box_metrics_copy(tmp_path: Path) -> None:
    pdf = pikepdf.new()
    desc = pdf.make_indirect(
        Dictionary(
            Type=Name.FontDescriptor,
            FontName=Name("/X"),
            Ascent=0,
            CapHeight=0,
            Descent=0,
            XHeight=431,
            FontBBox=Array([-50, -250, 1000, 900]),
        )
    )
    pdf.add_blank_page().obj.Resources = Dictionary(
        Font=Dictionary(F1=pdf.make_indirect(Dictionary(Type=Name.Font, FontDescriptor=desc)))
    )
    pdf.save(tmp_path / "a.pdf")
    out = box_metrics_copy(tmp_path / "a.pdf", tmp_path / "b.pdf")
    with pikepdf.open(out) as doc:
        (d,) = [
            o
            for o in doc.objects
            if isinstance(o, Dictionary) and o.get("/Type") == Name.FontDescriptor
        ]
        assert [int(d[k]) for k in ("/Ascent", "/CapHeight", "/Descent")] == [900, 900, -250]
        assert "/XHeight" not in d


def test_ref_widths_copy(tmp_path: Path) -> None:
    from chapmk.check import ref_widths_copy

    def pdf(path: Path, widths: list[float]) -> Path:
        doc = pikepdf.new()
        font = Dictionary(
            Type=Name.Font, BaseFont=Name("/ABCDEF+CMBX12"), FirstChar=62, Widths=Array(widths)
        )
        doc.add_blank_page().obj.Resources = Dictionary(Font=Dictionary(F1=doc.make_indirect(font)))
        doc.save(path)
        return path

    ref = pdf(tmp_path / "ref.pdf", [531.3, 531.3, 500.0])
    got = pdf(tmp_path / "got.pdf", [531.2, 530.0, 500.0])
    out = ref_widths_copy(ref, got, tmp_path / "out.pdf")
    with pikepdf.open(out) as doc:
        (font,) = [o for o in doc.objects if isinstance(o, Dictionary) and "/Widths" in o]
        assert [round(float(w), 1) for w in font.Widths] == [531.3, 530.0, 500.0]
