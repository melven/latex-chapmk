"""The tables of features that force full mode (design §1, §6.14)."""

from chapmk.facts import (
    UNSUPPORTED_PACKAGES,
    package_reason,
    runtime_reason,
    source_reasons,
)


def test_package_reasons() -> None:
    """Each unsupported package has its own reason, in the preamble and at run time."""
    assert package_reason("pdfx") == (
        "package 'pdfx' is not supported (PDF/A: writes its XMP file and PDF objects in the "
        "preamble)"
    )
    assert package_reason("minted", at_runtime=True).endswith(
        "(needs shell escape; loaded at runtime)"
    )
    assert all(UNSUPPORTED_PACKAGES.values())


def test_runtime_reason() -> None:
    """Packages a class or package loads (``.fls`` names), aux lines, missing companions."""
    assert runtime_reason({"book.cls", "bookmark.sty", "hyperref.sty"}, ["\\relax"]) is None
    assert "'perpage'" in (runtime_reason({"footmisc.sty", "perpage.sty"}, []) or "")
    assert "BibTeX in use" in (runtime_reason(set(), ["\\bibdata{refs}"]) or "")
    assert runtime_reason({"hyperref.sty"}, []) == (
        "hyperref without the bookmark package (the outline comes from bookmark's records; "
        "load bookmark to build incrementally)"
    )


def test_source_reasons() -> None:
    assert source_reasons("\\makeglossaries\n\\bibliography {refs}") == [
        "\\makeglossaries is not supported",
        "BibTeX (\\bibliography) is not supported; use biblatex with biber",
    ]
    assert source_reasons("\\makeglossariesx \\bibliographystyle{plain}") == []
