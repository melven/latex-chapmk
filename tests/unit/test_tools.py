"""Unit tests for tools.py: .bcf citations, patch, datalists, tool errors."""

from pathlib import Path

import pytest

from chapmk.tools import ToolInputError, citations_by_segment, patch_bcf

BCF = """<?xml?>
  <bcf:section number="0">
    <bcf:citekey order="1" intorder="1">a</bcf:citekey>
    <bcf:citekey order="2" intorder="1">b</bcf:citekey>
    <bcf:citekey order="2" intorder="2">c</bcf:citekey>
  </bcf:section>
"""


def test_citations_by_segment_and_patch() -> None:
    aux = [
        "\\chapmk@entry{G0}{}",
        "\\chapmk@gexit{G0}{}",
        "\\chapmk@entry{U1}{}",
        "\\abx@aux@cite{0}{a}",
        "\\chapmk@entry{G1}{}",
        "\\chapmk@gexit{G1}{}",
        "\\chapmk@entry{U2}{}",
        "\\abx@aux@cite{0}{b}",
        "\\abx@aux@cite{0}{c}",
        "\\chapmk@entry{G2}{}",
    ]
    cites = citations_by_segment(aux, BCF)
    assert [len(cites[s]) for s in ("G0", "U1", "G1", "U2", "G2")] == [0, 1, 0, 2, 0]
    elements = [(s, line) for s in ("U1", "U2") for line in cites[s]]
    assert patch_bcf(BCF, elements) == BCF
    # U2's elements before U1's: renumbered; equal original orders from different segments
    # stay separate commands
    swapped = [(s, line) for s in ("U2", "U1") for line in cites[s]]
    out = patch_bcf(BCF, swapped)
    assert '<bcf:citekey order="1" intorder="1">b<' in out
    assert '<bcf:citekey order="1" intorder="2">c<' in out
    assert '<bcf:citekey order="2" intorder="1">a<' in out
    same = [("U1", cites["U1"][0]), ("U2", cites["U1"][0])]
    assert patch_bcf(BCF, same).count('order="2"') == 1
    # no citations at all: elements inserted before the section end
    empty = BCF.replace(BCF[BCF.index("    <bcf:citekey") : BCF.index("  </bcf:section>")], "")
    assert patch_bcf(empty, elements) == BCF
    with pytest.raises(ToolInputError):
        citations_by_segment(aux[:4], BCF)
    with pytest.raises(ToolInputError):
        citations_by_segment(aux, BCF.replace('number="0"', 'number="1"'))


def test_bcf_datalists() -> None:
    """Datalists of a .bcf are read by section/name and replaced in sorted order."""
    from chapmk.tools import datalists, with_datalists

    dl = (
        '  <bcf:datalist section="0"\n                name="{}"\n  type="entry">\n  </bcf:datalist>'
    )
    bcf = (
        '<bcf:controlfile>\n  <bcf:section number="0">\n  </bcf:section>\n'
        + dl.format("b")
        + "\n</bcf:controlfile>\n"
    )
    assert list(datalists(bcf)) == ["0/b"]
    without = (
        '<bcf:controlfile>\n  <bcf:section number="0">\n  </bcf:section>\n</bcf:controlfile>\n'
    )
    assert datalists(without) == {}
    blocks = {"0/b": dl.format("b"), "0/a": dl.format("a")}
    merged = with_datalists(without, blocks)
    assert list(datalists(merged)) == ["0/a", "0/b"] and merged.endswith("</bcf:controlfile>\n")
    assert with_datalists(bcf, blocks) == merged
    assert with_datalists(bcf, datalists(bcf)) == bcf


def test_tool_error_lines(tmp_path: Path) -> None:
    """E7: the ERROR lines of a biber log and the errors of a makeindex transcript."""
    from chapmk.tools import biber_errors, makeindex_errors

    blg = tmp_path / "main.blg"
    blg.write_text(
        "[0] Config.pm:311> INFO - This is Biber 2.20\n"
        "[5] Utils.pm:418> WARN - something\n"
        "[9] Utils.pm:410> ERROR - BibTeX subsystem: x.utf8, line 6, syntax error\n"
    )
    assert biber_errors(blg) == ["BibTeX subsystem: x.utf8, line 6, syntax error"]
    assert biber_errors(tmp_path / "missing.blg") == []
    ilg = tmp_path / "main.ilg"
    ilg.write_text(
        "Scanning input file main.nlo....\n"
        "!! Input index error (file = main.nlo, line = 3):\n"
        "   -- Extra `@' at position 12 of first argument.\n"
        "done (1 entries accepted, 1 rejected).\n"
    )
    assert makeindex_errors(ilg) == [
        "!! Input index error (file = main.nlo, line = 3): -- Extra `@' at position 12 of first"
        " argument."
    ]


def test_bibtex_errors_and_inputs(tmp_path: Path) -> None:
    """E7: BibTeX's error lines; the inputs that decide whether it runs again (full mode)."""
    from chapmk.tools import bibtex_errors, bibtex_inputs

    blg = tmp_path / "main.blg"
    blg.write_text(
        "This is BibTeX, Version 0.99d\nThe top-level auxiliary file: main.aux\n"
        "I couldn't open database file nosuch.bib\n"
        "---line 3 of file main.aux\nWarning--empty journal in knuth84\n"
        "(There was 1 error message)\n"
    )
    assert bibtex_errors(blg) == [
        "I couldn't open database file nosuch.bib",
        "---line 3 of file main.aux",
    ]
    assert bibtex_errors(tmp_path / "missing.blg") == []
    out = tmp_path / "full"
    (out / "ch").mkdir(parents=True)
    (out / "main.aux").write_text("\\relax\n\\@input{ch/a.aux}\n\\bibstyle{plain}\n")
    (out / "ch" / "a.aux").write_text("\\relax\n\\citation{k1}\n")
    assert bibtex_inputs(out) is None  # no database: no BibTeX
    (out / "main.aux").write_text(
        "\\relax\n\\@input{ch/a.aux}\n\\bibstyle{plain}\n\\bibdata{refs}\n"
    )
    first = bibtex_inputs(out)
    assert first is not None
    (out / "ch" / "a.aux").write_text("\\relax\n\\citation{k1}\n\\newlabel{x}{{1}{1}}\n")
    assert bibtex_inputs(out) == first  # labels do not matter
    (out / "ch" / "a.aux").write_text("\\relax\n\\citation{k1}\n\\citation{k2}\n")
    assert bibtex_inputs(out) != first
