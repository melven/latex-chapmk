"""Unit tests for merge_pdf.py helpers."""

from pathlib import Path
from typing import Any

import pikepdf
from pikepdf import Array, Dictionary, Name

from chapmk.merge_pdf import _normalize_font_descriptors, label_style, page_labels


def test_page_labels() -> None:
    assert label_style(4, "iv") == "/r" and label_style(4, "IV") == "/R"
    assert label_style(2, "b") == "/a" and label_style(3, "3") == "/D"
    assert label_style(1, "A-1") is None
    nums = page_labels([(1, "i"), (2, "ii"), (1, "1"), (2, "2"), (5, "5"), (1, "A-1")])
    assert [int(n) if isinstance(n, int) else dict(n) for n in nums][::2] == [0, 2, 4, 5]
    assert str(nums[1].S) == "/r" and int(nums[5].St) == 5 and str(nums[7].P) == "A-1"


def _descriptor(pdf: Any, name: str, metrics: tuple[int, int, int, int], file: str) -> Any:
    desc = Dictionary(
        Type=Name.FontDescriptor, FontName=Name("/" + name), FontBBox=Array([-50, -250, 1000, 900])
    )
    for key, value in zip(("Ascent", "CapHeight", "Descent", "XHeight"), metrics, strict=True):
        desc[Name("/" + key)] = value
    desc[Name(file)] = pdf.make_stream(b"")
    return pdf.make_indirect(desc)


def _font(pdf: Any, desc: Any) -> Any:
    return pdf.make_indirect(
        Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=desc.FontName, FontDescriptor=desc)
    )


def test_font_descriptors_of_figures() -> None:
    """A font of the text that also occurs in an included PDF: the font file's metrics
    everywhere (pdfTeX replaces the figure's copy). A font only in figures keeps each
    figure's descriptor (pdfTeX copies it: a plot's ArialMT; sweep: 10 documents whose text
    check failed because the merge rewrote them)."""
    pdf = pikepdf.new()
    text = _descriptor(pdf, "ABCDEF+LMRoman10-Regular", (689, 689, -194, 431), "/FontFile")
    shared = _descriptor(pdf, "GHIJKL+LMRoman10-Regular", (689, 689, -194, 431), "/FontFile")
    arial = _descriptor(pdf, "MNOPQR+ArialMT", (905, 716, -212, 519), "/FontFile2")
    figure = pdf.make_stream(b"")
    figure.Type, figure.Subtype = Name.XObject, Name.Form
    figure[Name("/PTEX.FileName")] = pikepdf.String("plot.pdf")
    figure.Resources = Dictionary(Font=Dictionary(F1=_font(pdf, shared), F2=_font(pdf, arial)))
    page = pdf.add_blank_page()
    page.obj.Resources = Dictionary(
        Font=Dictionary(F3=_font(pdf, text)), XObject=Dictionary(X1=figure)
    )
    _normalize_font_descriptors(pdf)
    for d in (text, shared):
        assert [int(d[k]) for k in ("/Ascent", "/CapHeight", "/Descent")] == [900, 900, -250]
        assert "/XHeight" not in d
    assert [int(arial[k]) for k in ("/Ascent", "/CapHeight", "/Descent", "/XHeight")] == [
        905,
        716,
        -212,
        519,
    ]


XMP = (
    b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    b' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    b'  <rdf:Description rdf:about=""\n'
    b'     xmlns:pdf="http://ns.adobe.com/pdf/1.3/">\n'
    b"   <pdf:Producer></pdf:Producer>\n"
    b"   <pdf:PDFVersion>1.7</pdf:PDFVersion>\n"
    b"  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n"
    b'<?xpacket end="w"?>'
)


def test_xmp_metadata_and_version_are_kept(tmp_path: Path) -> None:
    """D1 (sweep): the catalog run's XMP stream (hyperxmp, pdfx) is copied unchanged and the
    merged file keeps that run's PDF version; pikepdf's default would rewrite the stream with
    pdf:PDFVersion set to its own version (1.3)."""
    from chapmk.merge_pdf import PageSource, merge_pdf

    run = tmp_path / "r1.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root.Metadata = pdf.make_stream(XMP, Type=Name.Metadata, Subtype=Name.XML)
    pdf.save(run, min_version="1.7", fix_metadata_version=False)
    merge_pdf([PageSource(run, 0, 1, "1", check_label=False)], [], run, tmp_path / "m.pdf")
    with pikepdf.open(tmp_path / "m.pdf") as merged:
        assert merged.pdf_version == "1.7"
        assert merged.Root.Metadata.read_bytes() == XMP
