from pathlib import Path

import pytest

from fastinc.analysis import analyse
from fastinc.config import Config
from fastinc.layout import make_layout
from fastinc.records import RecordError, parse_indices, parse_vector, read_run_records
from fastinc.runner import RUN_MAIN, RunSpec, prepare_run_dir


def project(tmp_path: Path) -> Config:
    src = tmp_path / "src"
    (src / "ch").mkdir(parents=True)
    (src / "ch" / "a.tex").write_text("\\chapter{A}")
    (src / "b.tex").write_text("\\chapter{B}")
    (src / "doc.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n\\include{ch/a}\n\\include{b}\n\\end{document}\n"
    )
    return Config(main=src / "doc.tex")


MAIN_AUX = r"""\relax
\fastinc@base{0=1,276=5,}
\fastinc@entry{G0}{}
\fastinc@gexit{G0}{0=3,}
\fastinc@abs{G0}{0,}
\fastinc@unit{U1}{ch/a.tex}
\fastinc@entry{U1}{0=3,}
\@input{ch/a.aux}
\fastinc@entry{G1}{0=7,276=6,}
\fastinc@gexit{G1}{0=7,276=6,}
\fastinc@abs{G1}{}
\fastinc@unit{U2}{}
\fastinc@entry{G2}{0=7,276=6,}
\fastinc@gexit{G2}{0=8,276=6,}
\fastinc@bkmlevels{1=0,2=1,}
"""
UNIT_AUX = "\\relax\n\\fastinc@ckpt{U1}{0=7,276=6,280=-2,}\n\\fastinc@abs{U1}{12,-1,}\n"
FREC = "F G0 /usr/x/book.cls\nP 0 G0 1 i\nP 1 U1 1 1\nP 2 U1 2 2\nF U1 ch/a.tex\nF U1 plot1.pdf\n"
NLO = "%fastinc-seg G0\n%fastinc-seg U1\n\\nomenclatureentry{A$x$}{1}\n%fastinc-seg G1\n"


def write_run(d: Path) -> None:
    (d / "ch").mkdir(parents=True)
    (d / "doc.aux").write_text(MAIN_AUX)
    (d / "ch" / "a.aux").write_text(UNIT_AUX)
    (d / "doc.frec").write_text(FREC)
    (d / "doc.nlo").write_text(NLO)


def test_parse_vector_and_indices() -> None:
    assert parse_vector("12=3,0=-1,") == {12: 3, 0: -1}
    assert parse_vector("") == {}
    assert parse_indices("3,-1,5,") == (3, 5)


def test_read_run_records(tmp_path: Path) -> None:
    a = analyse(project(tmp_path))
    d = tmp_path / "run"
    write_run(d)
    r = read_run_records(d, a)
    assert r.base == {0: 1, 276: 5}
    assert r.segments_in_order() == ["G0", "U1", "G1", "G2"]
    assert r.entry_state("G1") == {0: 7, 276: 6}
    assert r.glue_exits["G2"] == {0: 8, 276: 6}
    assert r.checkpoints["U1"] == {0: 7, 276: 6, 280: -2}
    assert r.absolute == {"G0": (0,), "G1": (), "U1": (12,)}
    assert r.units == {"U1": "ch/a.tex", "U2": ""}
    assert r.bookmark_levels == {1: 0, 2: 1}
    assert [(p.index, p.segment, p.value, p.label) for p in r.pages] == [
        (0, "G0", 1, "i"),
        (1, "U1", 1, "1"),
        (2, "U1", 2, "2"),
    ]
    assert ("U1", "plot1.pdf") in r.files
    assert r.nomenclature == {"G0": [], "U1": ["\\nomenclatureentry{A$x$}{1}"], "G1": []}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: (d / "doc.frec").unlink(), "missing"),
        (lambda d: (d / "doc.aux").write_text("\\relax\n"), "no baseline"),
        (
            lambda d: (d / "doc.aux").write_text(MAIN_AUX.replace("{ch/a.tex}", "{x.tex}")),
            "expected",
        ),
        (
            lambda d: (d / "doc.aux").write_text(MAIN_AUX.replace("\\fastinc@unit{U2}{}\n", "")),
            "include 2",
        ),
        (lambda d: (d / "doc.nlo").write_text("\\nomenclatureentry{x}{1}\n"), "before the first"),
    ],
)
def test_record_errors(tmp_path: Path, change, message: str) -> None:  # type: ignore[no-untyped-def]
    a = analyse(project(tmp_path))
    d = tmp_path / "run"
    write_run(d)
    change(d)
    with pytest.raises(RecordError, match=message):
        read_run_records(d, a)


def test_prepare_run_dir(tmp_path: Path) -> None:
    cfg = project(tmp_path)
    a = analyse(cfg)
    lay = make_layout(cfg, a)
    canon = tmp_path / "canon"
    (canon / "ch").mkdir(parents=True)
    for name in ("doc.aux", "ch/a.aux", "doc.toc", "doc.bbl", "doc.log", "other.aux"):
        (canon / name).write_text(name)
    d = prepare_run_dir(a, lay, RunSpec("r1", ("b",)), canon_dir=canon, deny_names=["x@y"])
    assert d == lay.runs_dir / "r1"
    files = {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()}
    assert files == {"doc.aux", "ch/a.aux", "doc.toc", "doc.bbl", RUN_MAIN}
    text = (d / RUN_MAIN).read_text()
    assert "\\includeonly{b}" in text and "{x@y}" in text
    (d / "stale").write_text("x")
    prepare_run_dir(a, lay, RunSpec("r1", None))
    assert not (d / "stale").exists() and (d / "ch").is_dir()
