"""Unit tests for state.py (state.json)."""

from pathlib import Path

import pytest

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
        units={"U1": UnitInputs({0: 3, 446: -1}, {"L:a": "h1"}, ".toc=h", True, [".toc"])},
        citations={"U1": ['<bcf:citekey order="1">k</bcf:citekey>']},
        aggregates={"G0": ["\\global\\csname @altsecnumformattrue\\endcsname"]},
        glue_inputs={"lists": "a", "labels": "b", "aux": "c"},
        pending={"U1": ["imports changed (L:a)"]},
        glue_pending="glue inputs changed (lists)",
        runtime_global={"U1": ["pagenumbering", "pagestyle"]},
        anchors={"U1": True, "G1": False},
        anchor_reads={"G1": [("addcontentsline", 12), ("label", 13)]},
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


def test_segment_ids() -> None:
    from chapmk.segment import (
        document_order,
        glue_id,
        is_glue,
        is_segment,
        is_unit,
        position,
        seg_index,
        unit_id,
    )

    order = document_order(2)
    assert order == ["G0", "U1", "G1", "U2", "G2"]
    assert [position(s) for s in order] == [0, 1, 2, 3, 4]
    assert sorted(["G2", "U2", "G0", "U1"], key=position) == ["G0", "U1", "U2", "G2"]
    assert unit_id(3) == "U3" and glue_id(0) == "G0" and seg_index("U12") == 12
    assert is_unit("U1") and not is_unit("G1") and not is_unit(None)
    assert is_glue("G0") and not is_glue("U1")
    assert is_segment("G10") and not is_segment("load") and not is_segment("U")
