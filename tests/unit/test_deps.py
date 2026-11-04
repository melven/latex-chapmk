"""Unit tests for deps.py: key values, token scan, imports."""

from pathlib import Path

from chapmk.deps import TokenScan, changed_imports, cite_values, imports, label_values


def test_label_and_cite_values(tmp_path: Path) -> None:
    v = label_values([["\\newlabel{a}{{1}{2}}", "\\newlabel{b:c}{{2}{", "5}}"]])
    assert set(v) == {"L:a", "L:b:c"}
    assert v != label_values([["\\newlabel{a}{{1}{3}}", "\\newlabel{b:c}{{2}{5}}"]])
    bbl = tmp_path / "x.bbl"
    bbl.write_text(
        "\\entry{k1}{article}{}\n\\field{year}{2000}\n\\endentry\n"
        "  \\entry{k2}{book}{}\n\\endentry\n"
    )
    c = cite_values(bbl)
    assert set(c) == {"C:k1", "C:k2"}
    bbl.write_text(
        "\\entry{k2}{book}{}\n\\endentry\n\\entry{k1}{article}{}\n\\field{year}{2000}\n\\endentry\n"
    )
    c2 = cite_values(bbl)
    assert c2["C:k1"] != c["C:k1"]  # position counts
    # keyed biblatex aux data (defernumbers) counts, citations and backrefs do not
    num = "\\abx@aux@number{2}{k1}{0}{nty/global//global/global/global}{1}"
    with_num = cite_values(bbl, [num, "\\abx@aux@cite{0}{k2}"])
    assert with_num["C:k1"] != c2["C:k1"] and with_num["C:k2"] == c2["C:k2"]
    assert cite_values(bbl, [num.replace("{1}", "{2}")])["C:k1"] != with_num["C:k1"]
    assert cite_values(bbl, ["\\abx@aux@backref{1}{k1}{0}{1}{1}"])["C:k1"] == c2["C:k1"]


def test_text_scan_imports() -> None:
    scan = TokenScan(["see \\ref{fig:a} and~\\cite[p.~3]{k1,k2}% \\ref{old}\n\\ref{with space}"])
    values = {
        "L:fig:a": "1",
        "L:fig:ab": "2",
        "C:k1": "3",
        "C:k3": "4",
        "L:old": "5",
        "L:with space": "6",
    }
    assert imports(scan, values) == {"L:fig:a": "1", "C:k1": "3", "L:old": "5", "L:with space": "6"}
    stored = {"L:fig:a": "1", "C:k1": "3"}
    assert changed_imports(stored, scan, {**values, "C:k2": "7"}) == [
        "C:k2",
        "L:old",
        "L:with space",
    ]
    assert changed_imports(stored, scan, {"L:fig:a": "1"}) == ["C:k1"]
    assert not TokenScan(["\\section{A}\\label{sec:a} text"]).references("L:sec:a")
    assert TokenScan(["\\label{sec:a} \\ref{sec:a}"]).references("L:sec:a")


def test_referenced_equals_references() -> None:
    """TokenScan.referenced (token lookup) gives the same keys as references (per key)."""
    scan = TokenScan(["see \\ref{fig:a} and~\\cite[p.~3]{k1,k2}% \\ref{old}\n\\ref{with space}"])
    keys = {
        "L:fig:a",
        "L:old",
        "L:with space",
        "L:unused",
        "C:k1",
        "C:k2",
        "C:k3",
        "L:k1",
        "L:fig",
        "C:with space",
        "L:a,b",
    }
    assert scan.referenced(keys) == {k for k in keys if scan.references(k)}
    assert scan.referenced(keys) >= {"L:fig:a", "L:with space", "C:k1", "C:k2"}


def test_list_reads() -> None:
    """List readers depend on the files they typeset; unknown list commands on all."""
    assert TokenScan(["\\printbibliography[heading=bibintoc]"]).list_reads() == {".bbl"}
    assert TokenScan(["\\tableofcontents\\listoffigures"]).list_reads() == {".toc", ".lof"}
    assert TokenScan(["\\makeatletter\\@starttoc{lol}"]).list_reads() == {".lol"}
    assert TokenScan(["\\listofexamples"]).list_reads() is None
    assert TokenScan(["\\section{A} text"]).list_reads() == set()
