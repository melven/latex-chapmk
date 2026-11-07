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
