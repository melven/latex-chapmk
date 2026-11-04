"""Unit tests for auxfile.py: statements, classes, keys, slices, bookmarks, canonical main aux."""

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
    bookmark_levels,
    canonical_main_aux,
    classify,
    parse_bookmark,
    run_input_main_aux,
    segment_slices,
    statement_key,
    statements,
    tex_octal_bytes,
)

MAIN_AUX = [
    "\\relax",
    "\\providecommand\\chapmk@base[1]{}",
    "\\chapmk@base{0=1,}",
    "\\chapmk@entry{G0}{}",
    "\\babel@aux{english}{}",
    "\\@input{ch1.aux}",
    "\\chapmk@gexit{G0}{}",
    "\\chapmk@abs{G0}{}",
    "\\chapmk@unit{U1}{ch1.tex}",
    "\\chapmk@entry{U1}{0=3,}",
    "\\BKM@entry{id=1,open,dest={636861707465722E31},srcline={1}}{5C3337365C3337375C3030304F}",
    "\\abx@aux@cite{0}{knuth}",
    "\\chapmk@entry{G1}{0=5,}",
    "\\@writefile{toc}{\\contentsline {chapter}{Bib}{5}{x}%",
    "}",
    "\\chapmk@bkmlevels{1=0,}",
]


def test_segment_slices_and_content() -> None:
    sl = segment_slices(MAIN_AUX)
    assert sl["G0"] == ["\\chapmk@entry{G0}{}", "\\babel@aux{english}{}", "\\@input{ch1.aux}"]
    assert sl["U1"][1].startswith("\\BKM@entry") and sl["U1"][2] == "\\abx@aux@cite{0}{knuth}"
    assert bookmark_levels(MAIN_AUX) == {1: 0}


def test_parse_bookmark() -> None:
    b = parse_bookmark(MAIN_AUX[10])
    assert b is not None and (b.id, b.open, b.dest) == (1, True, "chapter.1")
    assert b.title == b"\xfe\xff\x00O"
    assert parse_bookmark("\\relax") is None
    assert tex_octal_bytes(b"a\\376\\(b") == b"a\xfe(b"


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
