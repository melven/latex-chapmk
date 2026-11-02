"""Unit tests for the composition model and prediction (PLAN §6.9.3)."""

from fastinc.predict import (
    SegmentVectors,
    compose,
    normalized,
    partition,
    predict,
    rewrite_checkpoint,
)


def test_compose_relative_and_absolute() -> None:
    # page (0) and a link counter (514) count on; the chapter resets section (279)
    seg = SegmentVectors({0: 5, 279: 3, 514: 10}, {0: 9, 279: 2, 514: 13}, frozenset({279}))
    assert compose(seg, {0: 6, 279: 7, 514: 10}) == {0: 10, 279: 2, 514: 13}
    assert compose(seg, seg.entry) == seg.exit
    # missing registers are 0; zeros are dropped
    assert compose(SegmentVectors({}, {1: 1}, frozenset()), {1: -1}) == {}
    assert normalized({1: 0, 2: 3}) == {2: 3}


def test_predict_chains_segments() -> None:
    vectors = {
        "U1": SegmentVectors({0: 1}, {0: 5}, frozenset()),
        "G1": SegmentVectors({0: 5}, {0: 5}, frozenset()),
        "U2": SegmentVectors({0: 5}, {0: 9}, frozenset()),
        "G2": SegmentVectors({0: 9}, {0: 10}, frozenset()),
    }
    p = predict(["U1", "G1", "U2", "G2"], vectors, "U1", {0: 2})
    assert p["U1"] == ({0: 2}, {0: 6})
    assert p["U2"] == ({0: 6}, {0: 10})
    assert p["G2"][1] == {0: 11}
    assert set(predict(["U1", "G1", "U2", "G2"], vectors, "U2", {0: 5})) == {"U2", "G2"}


def test_partition_contiguous_balanced() -> None:
    assert partition([1, 1, 1, 1], 2) == [[0, 1], [2, 3]]
    assert partition([5, 1, 1, 1, 1, 1], 2) == [[0], [1, 2, 3, 4, 5]]
    assert partition([1, 1], 4) == [[0], [1]]
    assert partition([3, 3, 3], 1) == [[0, 1, 2]]
    groups = partition([2, 2, 2, 2, 2, 2, 2, 2], 4)
    assert len(groups) == 4 and [i for g in groups for i in g] == list(range(8))


def test_modified_registers() -> None:
    from fastinc.predict import modified

    seg = SegmentVectors({0: 5, 7: 3, 8: 2, 9: 1}, {0: 9, 7: 3, 8: 2}, frozenset({8}))
    # 0 changes, 8 is assigned absolutely, 9 is reset to 0; 7 and all registers that are 0 at
    # both ends (missing) pass through
    assert modified(seg) == {0, 8, 9}


def test_rewrite_checkpoint_keeps_only_modified() -> None:
    stmts = [
        "\\fastinc@ckpt{U1}{0=6,154=1,300=4,}",
        "\\@setckpt{ch1}{\n\\setcounter{page}{6}\n\\setcounter{maxextraname}{4}\n}",
    ]
    out = rewrite_checkpoint(
        stmts, {0: 8, 154: 1, 300: 4}, {"page": 0, "maxextraname": 300}, frozenset({0, 154})
    )
    assert out[0] == "\\fastinc@ckpt{U1}{0=8,154=1,}"
    assert "maxextraname" not in out[1] and "\\setcounter{page}{8}" in out[1]
    assert "\n\n" not in out[1]


def test_rewrite_checkpoint() -> None:
    stmts = [
        "\\relax",
        "\\fastinc@ckpt{U1}{0=6,154=1,278=1,}",
        "\\@setckpt{chapters/ch1}{\n\\setcounter{page}{6}\n\\setcounter{equation}{1}\n"
        "\\setcounter{mystery}{4}\n}",
    ]
    out = rewrite_checkpoint(stmts, {0: 8, 278: 1, 514: 3}, {"page": 0, "equation": 154})
    assert out[0] == "\\relax"
    assert out[1] == "\\fastinc@ckpt{U1}{0=8,154=0,278=1,514=3,}"
    assert "\\setcounter{page}{8}" in out[2] and "\\setcounter{equation}{0}" in out[2]
    assert "\\setcounter{mystery}{4}" in out[2]  # unknown counter: unchanged


def test_compose_odd_start_page() -> None:
    # chapter in twoside/openright: entry page 6 (blank page 6, start 7), 4 content pages
    seg = SegmentVectors({0: 6}, {0: 11}, frozenset())
    assert compose(seg, {0: 7}, odd=True) == {0: 11}  # no blank page any more
    assert compose(seg, {0: 8}, odd=True) == {0: 13}  # blank page again, start 9
    assert compose(seg, {0: 7}) == {0: 12}  # linear model without the flag


def test_list_sections_and_splice() -> None:
    from fastinc.canon import splice_list, unit_sections

    base = (
        "\\fastinc@lmark {/G0}\nfront\n\\fastinc@lmark {U1}\nold a\n\\fastinc@lmark {/U1}\n"
        "\\fastinc@lmark {/G1}\n\\fastinc@lmark {U2}\nb\n\\fastinc@lmark {/U2}\nend\n"
    )
    assert unit_sections(base) == {"U1": ["old a\n"], "U2": ["b\n"]}
    out = splice_list(base, {"U1": ["new a\n", "new a2\n"]})
    assert out is not None and "new a\nnew a2\n\\fastinc@lmark {/U1}" in out and "old a" not in out
    assert out.endswith("b\n\\fastinc@lmark {/U2}\nend\n")
    assert splice_list(base, {"U3": ["x\n"]}) is None  # no markers for U3
    assert splice_list(base, {}) == base


def test_list_extensions_match_the_driver() -> None:
    import re
    from pathlib import Path

    from fastinc.canon import LIST_SUFFIXES

    sty = (Path(__file__).parents[2] / "src/fastinc/tex/fastinc.sty").read_text()
    m = re.search(r"\\providecommand\\fastinc@listexts\{([^}]*)\}", sty)
    assert m is not None
    assert [f".{e}" for e in m.group(1).split(",")] == list(LIST_SUFFIXES)


def test_tex_phases_and_timings() -> None:
    from fastinc.records import RunRecords, tex_phases
    from fastinc.timing import Timings

    recs = RunRecords(
        times=[("load", 0.5), ("begin", 0.8), ("G0", 0.8), ("U1", 1.0), ("G1", 1.5), ("end", 1.6)]
    )
    nested = RunRecords(
        times=[
            ("load", 0.1),
            ("begin", 0.2),
            ("G0", 0.2),
            ("U1", 0.3),
            ("picture+", 0.4),
            ("picture+", 0.5),
            ("picture-", 0.6),
            ("picture-", 0.9),
            ("G1", 1.0),
        ]
    )
    assert tex_phases(nested, 1.0)["pictures"] == 0.5 and tex_phases(nested, 1.0)["units"] == 0.7
    assert tex_phases(recs, 2.0) == {
        "format": 0.5,
        "preamble": 0.3,
        "glue": 0.3,
        "units": 0.5,
        "end": 0.4,
        "pictures": 0.0,
    }
    assert tex_phases(RunRecords(), 1.0)["format"] == 0.0
    from fastinc.records import glue_times

    assert glue_times(recs) == {"G0": 0.2, "G1": 0.1}
    assert glue_times(recs, minimum=0.15) == {"G0": 0.2}
    t = Timings()
    t.lap("a")
    t.lap("a")
    assert set(t.as_dict()) == {"a"}
