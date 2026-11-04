"""Unit tests for the M4 modules: aux statements, dependency model, tools, lint."""

from pathlib import Path

import pytest

from chapmk.auxfile import (
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
    run_input_main_aux,
    statement_key,
    statements,
)
from chapmk.deps import TokenScan, changed_imports, cite_values, imports, label_values
from chapmk.lint import lint_text
from chapmk.tools import ToolInputError, citations_by_segment, patch_bcf

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


def test_counter_records_and_reset_closure() -> None:
    from chapmk.records import RunRecords, parse_counters

    c = parse_counters(
        "chapter=279:section/figure/;section=280:subsection/;subsection=281:;"
        "figure=284:subfigure/;subfigure=490:;page=0:;"
    )
    assert c["chapter"] == (279, ("section", "figure")) and c["page"] == (0, ())
    recs = RunRecords(counters=c)
    assert recs.reset_registers("chapter") == {280, 281, 284, 490}
    assert recs.reset_registers("page") == set() and recs.reset_registers("nope") == set()


def test_biblatex_instcount_is_not_data() -> None:
    a = "\\abx@aux@number{2}{k}{0}{ctx}{1}"
    b = "\\abx@aux@number{7}{k}{0}{ctx}{1}"
    assert statement_key(a) == statement_key(b) == "\\abx@aux@number{}{k}{0}{ctx}"
    assert run_input_main_aux(
        [
            "\\chapmk@entry{U1}{}",
            "\\abx@aux@cite{0}{x}",
            "\\BKM@entry{id=1}{41}",
            "\\chapmk@entry{U2}{}",
            "\\abx@aux@cite{0}{y}",
        ],
        {"U1"},
    ) == [
        "\\chapmk@entry{U1}{}",
        "\\BKM@entry{id=1}{41}",
        "\\chapmk@entry{U2}{}",
        "\\abx@aux@cite{0}{y}",
    ]


def test_canonical_main_aux_keeps_unit_content_of_excluded_units() -> None:
    old = [
        "\\relax",
        "\\chapmk@entry{G0}{}",
        "\\chapmk@gexit{G0}{}",
        "\\chapmk@unit{U1}{a.tex}",
        "\\chapmk@entry{U1}{1=1,}",
        "\\abx@aux@cite{0}{k1}",
        "\\BKM@entry{id=1,dest={41}}{41}",
        "\\abx@aux@category{lit}{k1}",
        "\\chapmk@entry{G1}{}",
        "\\expandafter\\gdef\\csname eqp@this@A\\endcsname{1pt}",
        "\\expandafter\\gdef\\csname eqp@this@B\\endcsname{2pt}",
        "\\chapmk@gexit{G1}{}",
        "\\global\\csname @altsecnumformattrue\\endcsname",
        "\\abx@aux@defaultrefcontext{0}{k1}{c}",
        "\\gdef \\@abspage@last{10}",
    ]
    run = [
        "\\relax",
        "\\chapmk@entry{G0}{}",
        "\\chapmk@gexit{G0}{}",
        "\\chapmk@unit{U1}{a.tex}",
        "\\chapmk@entry{U1}{1=1,}",
        "\\@writefile{toc}{\\addvspace}",  # delayed glue write: stays
        "\\chapmk@entry{G1}{}",
        "\\expandafter\\gdef\\csname eqp@this@B\\endcsname{3pt}",
        "\\chapmk@gexit{G1}{}",
        "\\gdef \\@abspage@last{4}",
    ]
    out = canonical_main_aux(
        run, old, {"U1"}, ["\\global\\csname @altsecnumformattrue\\endcsname"], 12
    )
    i = out.index("\\chapmk@entry{U1}{1=1,}")
    assert out[i + 1 : i + 4] == [
        "\\abx@aux@cite{0}{k1}",
        "\\BKM@entry{id=1,dest={41}}{41}",
        "\\abx@aux@category{lit}{k1}",
    ]
    assert out.count("\\abx@aux@category{lit}{k1}") == 1
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
    # configured verbatim environments and short verbatim characters (pgf manual)
    code = "\\begin{codeexample}[preamble={\\usetikzlibrary{x}}]\n\\def\\a{}\n\\end{codeexample}"
    assert _cmds(code) != [] and lint_text(code, "u.tex", verbatim=("codeexample",)) == []
    short = "write |\\def\\pgfsysdriver{x}| somewhere\n|unclosed \\pagestyle{empty}"
    assert [h.command for h in lint_text(short, "u.tex", shortverb=("|",))] == ["\\pagestyle"]
    assert "wrap it in a group" in lint_text("\\def\\x{}", "u.tex")[0].message()
    assert "move it to the preamble" in lint_text("\\appendix", "u.tex")[0].message()


# --- graph ---------------------------------------------------------------------------------


def test_graph_renderers() -> None:
    from chapmk.graph import Graph, IncludeNode, to_dot, to_json, to_text

    g = Graph(
        units=[["a"], ["b", "b2"]],
        includes=[
            IncludeNode("a", "U1", 1, ["a.tex"], {"b": ["sec:x"], "bibliography": ["k"]}, [], []),
            IncludeNode("b", "U2", 2, ["b.tex"], {}, ["b.tex:3: \\setlength ..."], ["x"]),
            IncludeNode("b2", "U3", 2, [], {}, [], []),
        ],
    )
    text = to_text(g)
    assert "unit 2: b, b2 [global]" in text and "imports from b: sec:x" in text
    assert "dirty: x" in text and "files: -" in text
    dot = to_dot(g)
    assert '"b" -> "a" [label="1"];' in dot and '"a" -> "b" [style=dashed];' in dot
    assert "cluster_2" in dot and "color=red" in dot
    assert '"units"' in to_json(g)


def test_graph_without_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from chapmk.cli import main

    (tmp_path / "d.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert main(["graph", "d.tex"], cwd=tmp_path) == 2
    assert "run 'chapmk build' first" in capsys.readouterr().err


# --- planning ------------------------------------------------------------------------------


def _planner(n: int, groups: list[list[int]], global_units: set[int]):  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    from chapmk.incremental import Fixpoint

    fp = object.__new__(Fixpoint)
    fp.units = [f"U{k}" for k in range(1, n + 1)]
    fp.group = {k: g for g in groups for k in g}
    fp.a = SimpleNamespace(includes=[SimpleNamespace(arg=f"c{k}") for k in range(1, n + 1)])
    fp.is_global = lambda seg: int(seg[1:]) in global_units  # type: ignore[method-assign]
    return fp


def test_plan_groups_and_global_units() -> None:
    fp = _planner(5, [[1], [2, 3], [4], [5]], set())
    assert fp.plan({"U3": ["x"]})[0] == [2, 3]
    assert fp.plan({})[0] == []  # glue only
    assert fp.plan({f"U{k}": ["x"] for k in range(1, 6)})[0] is None
    # a global unit is in every run; when dirty itself, all later units join
    fp = _planner(5, [[1], [2], [3], [4], [5]], {2})
    sel, reasons = fp.plan({"U4": ["sources changed"]})
    assert sel == [2, 4] and "compiled in every run" in reasons["U2"][0]
    sel, reasons = fp.plan({"U2": ["sources changed"]})
    assert sel == [2, 3, 4, 5] and "follows the global unit c2" in reasons["U5"][0]
    assert fp.plan({})[0] == [2]


def test_register_names(tmp_path: Path) -> None:
    from chapmk.records import register_names

    log = tmp_path / "x.log"
    log.write_text(
        "\\c@figure=\\count284\n"
        "(/usr/share/texmf/tex/latex/hyperref/hyperref.sty Package: hyperref (see notes)\n"
        "\\Hy@linkcounter=\\count514\n"
        "(/usr/share/texmf/tex/latex/hyperref/nameref.sty\n\\c@section@level=\\count515\n)\n"
        "\\Hy@x=\\count516\n"
        ")\nother line\n\\c@later=\\count517\n"
    )
    assert register_names([log, tmp_path / "missing.log"]) == {
        284: "\\c@figure",
        514: "\\Hy@linkcounter [hyperref]",
        515: "\\c@section@level [nameref]",
        516: "\\Hy@x [hyperref]",
        517: "\\c@later",
    }


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


def test_lint_cache(tmp_path: Path) -> None:
    """Cached hits equal fresh ones; a changed file or changed options are linted again."""
    from chapmk.lint import lint_files

    (tmp_path / "a.tex").write_text("\\chapter{A}\n\\def\\x{1}\n")
    cache: dict[str, list[list[object]]] = {}
    first = lint_files(tmp_path, ["a.tex"], cache=cache)  # type: ignore[arg-type]
    assert len(cache) == 1 and first
    assert lint_files(tmp_path, ["a.tex"], cache=cache) == first  # type: ignore[arg-type]
    assert lint_files(tmp_path, ["a.tex"], allow=["def"], cache=cache) == []  # type: ignore[arg-type]
    (tmp_path / "a.tex").write_text("\\chapter{A}\n")
    assert lint_files(tmp_path, ["a.tex"], cache=cache) == []  # type: ignore[arg-type]
    assert len(cache) == 3


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


def test_list_reads() -> None:
    """List readers depend on the files they typeset; unknown list commands on all."""
    assert TokenScan(["\\printbibliography[heading=bibintoc]"]).list_reads() == {".bbl"}
    assert TokenScan(["\\tableofcontents\\listoffigures"]).list_reads() == {".toc", ".lof"}
    assert TokenScan(["\\makeatletter\\@starttoc{lol}"]).list_reads() == {".lol"}
    assert TokenScan(["\\listofexamples"]).list_reads() is None
    assert TokenScan(["\\section{A} text"]).list_reads() == set()


def test_glue_hints() -> None:
    """Slow glue blocks: the part from the first chapter-level heading or list command can be
    \\include'd (state commands before it stay; list commands need a units.heading entry);
    otherwise the reason; fast blocks: nothing."""
    from chapmk.lint import glue_hints

    lines = [
        "\\documentclass{book}\n",  # 1
        "\\begin{document}\n",  # 2
        "\\tableofcontents\n",  # 3   G0 (fast)
        "\\include{a}\n",  # 4
        "\\appendix\n",  # 5          G1: \appendix stays, \chapter movable
        "\\chapter{Extra}\n",  # 6
        "\\include{b}\n",  # 7
        "\\backmatter\n",  # 8        G2: as in the reference document
        "\n",  # 9
        "% comment\n",  # 10
        "\\printbibliography\n",  # 11
        "\\include{c}\n",  # 12
        "Some text\\par\n",  # 13      G3: no heading
        "\\end{document}\n",
    ]
    hints = glue_hints(
        "main.tex", lines, 2, [4, 7, 12], {"G0": 0.1, "G1": 0.7, "G2": 1.8, "G3": 0.9}, ["chapter"]
    )
    assert len(hints) == 3
    assert hints[0].startswith("main.tex:5-6: glue (\\appendix) takes 0.7 s")
    assert "lines 6-6 (from \\chapter) moved" in hints[0] and "(lines 5-5 stay)" in hints[0]
    assert hints[1].startswith("main.tex:8-11: glue (\\backmatter) takes 1.8 s")
    assert "lines 11-11 (from \\printbibliography) moved" in hints[1]
    assert '[units] heading = ["printbibliography"] (lines 8-10 stay)' in hints[1]
    assert "no chapter-level heading" in hints[2]
    grouped = ["\\begin{document}\n", "\\chapter{X}\\begingroup\n", "\\include{a}\n"]
    [hint] = glue_hints("m.tex", grouped, 1, [3], {"G0": 1.0}, ["chapter"])
    assert "group or environment is open" in hint
    stateful = ["\\begin{document}\n", "\\chapter{X}\\pagestyle{empty}\n", "\\include{a}\n"]
    [hint] = glue_hints("m.tex", stateful, 1, [3], {"G0": 1.0}, ["chapter"])
    assert "contains \\pagestyle" in hint


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
