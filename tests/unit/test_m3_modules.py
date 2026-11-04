"""Unit tests for state.py, auxfile.py, merge_pdf label helpers and the SyncTeX merge."""

from pathlib import Path

import pytest

from chapmk.auxfile import (
    bookmark_levels,
    parse_bookmark,
    segment_slices,
    tex_octal_bytes,
)
from chapmk.merge_pdf import label_style, page_labels
from chapmk.state import (
    STATE_FILE,
    STATE_VERSION,
    CorruptStateError,
    SegmentArtifact,
    State,
    UnitInputs,
    load_state,
    save_state,
)
from chapmk.synctex import SyncTexError, merge, parse, write_lines


def test_state_round_trip(tmp_path: Path) -> None:
    s = State(
        1700000000,
        {"pre": "a", "post": "b", "body": "c"},
        "stamp",
        ["ch1"],
        {"G0": SegmentArtifact("r1", (0, 1)), "U1": SegmentArtifact("r2", ())},
        {"U1": {"ch1.tex": "h"}},
        {"refs.bib": "g"},
        next_run=3,
        units={"U1": UnitInputs({0: 3, 446: -1}, {"L:a": "h1"}, None, True)},
        citations={"U1": ['<bcf:citekey order="1">k</bcf:citekey>']},
        aggregates={"G0": ["\\global\\csname @altsecnumformattrue\\endcsname"]},
        glue_inputs="lists=a;labels=b;aux=c",
        pending={"U1": ["imports changed (L:a)"]},
        glue_pending="glue inputs changed (lists)",
        dist_files={"/texmf/tex/latex/pgf.sty": "120:1700000000000000000"},
    )
    save_state(s, tmp_path)
    t = load_state(tmp_path)
    assert t == s and t is not None and t.run_names() == {"r1", "r2"}
    assert t.new_run_name() == "r3" and t.next_run == 4
    assert load_state(tmp_path / "missing") is None
    (tmp_path / STATE_FILE).write_text('{"version": 999}')
    assert load_state(tmp_path) is None
    (tmp_path / STATE_FILE).write_text(f'{{"version": {STATE_VERSION}}}')
    with pytest.raises(CorruptStateError, match="unreadable"):  # E7: a cold build
        load_state(tmp_path)


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


def test_page_labels() -> None:
    assert label_style(4, "iv") == "/r" and label_style(4, "IV") == "/R"
    assert label_style(2, "b") == "/a" and label_style(3, "3") == "/D"
    assert label_style(1, "A-1") is None
    nums = page_labels([(1, "i"), (2, "ii"), (1, "1"), (2, "2"), (5, "5"), (1, "A-1")])
    assert [int(n) if isinstance(n, int) else dict(n) for n in nums][::2] == [0, 2, 4, 5]
    assert str(nums[1].S) == "/r" and int(nums[5].St) == 5 and str(nums[7].P) == "A-1"


def synctex_file(path: Path, main: str, sheets: int) -> None:
    lines = [
        "SyncTeX Version:1",
        f"Input:1:{main}",
        "Input:2:/tex/a.sty",
        "Output:pdf",
        "Magnification:1000",
        "Unit:1",
        "X Offset:0",
        "Y Offset:0",
        "Content:",
    ]
    for n in range(1, sheets + 1):
        lines += ["!0", f"{{{n}", f"[1,{n}:0,0:10,10,0", "x2,5:1,1", "]", "!0", f"}}{n}"]
    lines += ["!0", "Postamble:", "Count:1", "!0", "Post scriptum:"]
    write_lines(path, lines)


def test_synctex_merge(tmp_path: Path) -> None:
    a, b = tmp_path / "a.synctex.gz", tmp_path / "b.synctex.gz"
    synctex_file(a, "/build/runs/r1/chapmk-run.tex", 3)
    synctex_file(b, "/build/runs/r2/chapmk-run.tex", 2)
    out = tmp_path / "m.synctex.gz"
    merge(
        [(a, 0), (b, 1), (a, 2)],
        lambda p: "/src/./main.tex" if p.endswith("chapmk-run.tex") else p,
        out,
    )
    m = parse(out)
    assert m.inputs == {"1": "/src/./main.tex", "2": "/tex/a.sty"}
    assert sorted(m.sheets) == [1, 2, 3]
    assert m.sheets[2][0] == "[1,2:0,0:10,10,0" and m.sheets[3][1] == "x2,5:1,1"
    assert m.header["Magnification"] == "1000"
    synctex_file(b, "/x", 1)
    with pytest.raises(SyncTexError, match="no sheet"):
        merge([(b, 4)], str, out)
