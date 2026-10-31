"""Unit tests for the M4 modules: aux statements, dependency model, tools, lint."""

from pathlib import Path

import pytest

from fastinc.aux import (
    ABSPAGE,
    AGGREGATE,
    BIBDATA,
    CITE,
    EQP,
    GLOBAL,
    LABEL,
    LISTDATA,
    SELF,
    canonical_main_aux,
    classify,
    statement_key,
    statements,
)
from fastinc.deps import TokenScan, bbl_values, changed_imports, imports, label_values
from fastinc.lint import lint_text
from fastinc.tools import ToolInputError, citations_by_segment, patch_bcf

# --- aux statements ------------------------------------------------------------------------


def test_statements_join_multiline_records() -> None:
    lines = [
        "\\relax",
        "\\@setckpt{ch1}{",
        "\\setcounter{page}{3}",
        "}",
        "\\gdef \\LT@i {\\LT@entry ",
        "    {3}{42.5pt}}",
        "\\newlabel{a}{{1}{2}}",
        "\\@writefile{toc}{\\{x}",  # escaped brace does not count
    ]
    st = statements(lines)
    assert len(st) == 5
    assert st[1].startswith("\\@setckpt") and st[1].endswith("}")
    assert classify(st[2]) == SELF and classify(st[3]) == LABEL


@pytest.mark.parametrize(
    ("stmt", "kind"),
    [
        ("\\abx@aux@cite{0}{ref01}", CITE),
        ("\\abx@aux@segm{0}{0}{ref01}", CITE),
        ("\\abx@aux@defaultrefcontext{0}{ref01}{nty/global//global/global/global}", BIBDATA),
        ("\\pgfsyspdfmark {pgfid3}{22496944}{10432976}", SELF),
        ("\\expandafter\\gdef\\csname eqp@this@C1.1\\endcsname{77.988pt}", EQP),
        ("\\global\\csname @altsecnumformattrue\\endcsname", AGGREGATE),
        ("\\global\\@namedef{scr@dte@chapter@lastmaxnumwidth}{12.8pt}", LISTDATA),
        ("\\gdef \\@abspage@last{63}", ABSPAGE),
        ("\\mysterious{1}", GLOBAL),
    ],
)
def test_classify(stmt: str, kind: str) -> None:
    assert classify(stmt) == kind


def test_statement_key() -> None:
    assert statement_key("\\abx@aux@defaultrefcontext{0}{k}{ctx}") == (
        "\\abx@aux@defaultrefcontext{0}{k}"
    )
    assert statement_key("\\expandafter\\gdef\\csname eqp@this@T\\endcsname{1pt}") == (
        "\\expandafter\\gdef\\csname eqp@this@T\\endcsname"
    )


def test_canonical_main_aux_keeps_unit_content_of_excluded_units() -> None:
    old = [
        "\\relax",
        "\\fastinc@entry{G0}{}",
        "\\fastinc@gexit{G0}{}",
        "\\fastinc@unit{U1}{a.tex}",
        "\\fastinc@entry{U1}{1=1,}",
        "\\abx@aux@cite{0}{k1}",
        "\\BKM@entry{id=1,dest={41}}{41}",
        "\\fastinc@entry{G1}{}",
        "\\expandafter\\gdef\\csname eqp@this@A\\endcsname{1pt}",
        "\\expandafter\\gdef\\csname eqp@this@B\\endcsname{2pt}",
        "\\fastinc@gexit{G1}{}",
        "\\global\\csname @altsecnumformattrue\\endcsname",
        "\\abx@aux@defaultrefcontext{0}{k1}{c}",
        "\\gdef \\@abspage@last{10}",
    ]
    run = [
        "\\relax",
        "\\fastinc@entry{G0}{}",
        "\\fastinc@gexit{G0}{}",
        "\\fastinc@unit{U1}{a.tex}",
        "\\fastinc@entry{U1}{1=1,}",
        "\\@writefile{toc}{\\addvspace}",  # delayed glue write: stays
        "\\fastinc@entry{G1}{}",
        "\\expandafter\\gdef\\csname eqp@this@B\\endcsname{3pt}",
        "\\fastinc@gexit{G1}{}",
        "\\gdef \\@abspage@last{4}",
    ]
    out = canonical_main_aux(
        run, old, {"U1"}, ["\\global\\csname @altsecnumformattrue\\endcsname"], 12
    )
    i = out.index("\\fastinc@entry{U1}{1=1,}")
    assert out[i + 1 : i + 3] == ["\\abx@aux@cite{0}{k1}", "\\BKM@entry{id=1,dest={41}}{41}"]
    assert "\\@writefile{toc}{\\addvspace}" in out
    assert "\\expandafter\\gdef\\csname eqp@this@B\\endcsname{3pt}" in out
    assert "\\expandafter\\gdef\\csname eqp@this@A\\endcsname{1pt}" in out
    assert "\\expandafter\\gdef\\csname eqp@this@B\\endcsname{2pt}" not in out
    assert "\\abx@aux@defaultrefcontext{0}{k1}{c}" in out
    assert out.count("\\global\\csname @altsecnumformattrue\\endcsname") == 1
    assert out[-1] == "\\gdef \\@abspage@last{12}"


# --- dependency model ----------------------------------------------------------------------


def test_label_and_cite_values(tmp_path: Path) -> None:
    v = label_values([["\\newlabel{a}{{1}{2}}", "\\newlabel{b:c}{{2}{", "5}}"]])
    assert set(v) == {"L:a", "L:b:c"}
    assert v != label_values([["\\newlabel{a}{{1}{3}}", "\\newlabel{b:c}{{2}{5}}"]])
    bbl = tmp_path / "x.bbl"
    bbl.write_text(
        "\\entry{k1}{article}{}\n\\field{year}{2000}\n\\endentry\n"
        "  \\entry{k2}{book}{}\n\\endentry\n"
    )
    c = bbl_values(bbl)
    assert set(c) == {"C:k1", "C:k2"}
    bbl.write_text(
        "\\entry{k2}{book}{}\n\\endentry\n\\entry{k1}{article}{}\n\\field{year}{2000}\n\\endentry\n"
    )
    c2 = bbl_values(bbl)
    assert c2["C:k1"] != c["C:k1"]  # position counts


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
    assert not TokenScan(["text"]).reads_lists()
    assert TokenScan(["\\listoffigures"]).reads_lists()


# --- tools ---------------------------------------------------------------------------------

BCF = """<?xml?>
  <bcf:section number="0">
    <bcf:citekey order="1" intorder="1">a</bcf:citekey>
    <bcf:citekey order="2" intorder="1">b</bcf:citekey>
    <bcf:citekey order="2" intorder="2">c</bcf:citekey>
  </bcf:section>
"""


def test_citations_by_segment_and_patch() -> None:
    aux = [
        "\\fastinc@entry{G0}{}",
        "\\fastinc@gexit{G0}{}",
        "\\fastinc@entry{U1}{}",
        "\\abx@aux@cite{0}{a}",
        "\\fastinc@entry{G1}{}",
        "\\fastinc@gexit{G1}{}",
        "\\fastinc@entry{U2}{}",
        "\\abx@aux@cite{0}{b}",
        "\\abx@aux@cite{0}{c}",
        "\\fastinc@entry{G2}{}",
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


# --- lint ----------------------------------------------------------------------------------


def _cmds(text: str, allow: tuple[str, ...] = ()) -> list[tuple[int, str, bool]]:
    return [(h.line, h.command, h.is_global) for h in lint_text(text, "u.tex", allow)]


def test_lint_local_commands_outside_groups() -> None:
    assert _cmds("\\chapter{A}\n\\setlength{\\parindent}{0pt}\n") == [(2, "\\setlength", False)]
    assert _cmds("\\begin{table}\\setlength{\\tabcolsep}{1pt}\\end{table}") == []
    assert _cmds("{\\setlength{\\parskip}{0pt} x}") == []
    assert _cmds("\\begingroup\\def\\x{1}\\endgroup") == []
    # braces after a control word, } or ] are arguments, not groups
    assert _cmds("\\ifdraft{\\def\\x{1}}{}") == [(1, "\\def", False)]
    assert _cmds("\\foo[o]{\\let\\a\\b}") == [(1, "\\let", False)]
    # inside an argument inside a real group: grouped
    assert _cmds("\\begin{figure}\\ifdraft{\\def\\x{1}}{}\\end{figure}") == []
    # after the group closed
    assert _cmds("{\\small x}\n\\def\\y{2}") == [(2, "\\def", False)]


def test_lint_global_commands_comments_verbatim_allow() -> None:
    assert _cmds("{\\global\\def\\x{1}}") == [(1, "\\global\\def", True)]
    assert _cmds("\\begin{table}\\newcounter{c}\\end{table}") == [(1, "\\newcounter", True)]
    assert _cmds("% \\def\\x{1}\ntext 50\\% \\pagestyle{empty}") == [(2, "\\pagestyle", True)]
    assert _cmds("\\begin{verbatim}\n\\def\\x{1}\n\\end{verbatim}\n\\verb|\\def| x") == []
    assert _cmds("\\setlength{\\a}{1pt}", allow=("\\setlength",)) == []
    assert "wrap it in a group" in lint_text("\\def\\x{}", "u.tex")[0].message()
    assert "move it to the preamble" in lint_text("\\appendix", "u.tex")[0].message()
