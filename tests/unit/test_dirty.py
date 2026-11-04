"""Unit tests for dirty.py: the dirty rules after a batch (no TeX)."""

from pathlib import Path

from chapmk.analysis import analyse
from chapmk.canon import CanonView
from chapmk.config import Config
from chapmk.deps import TokenScan
from chapmk.dirty import DirtyRules
from chapmk.records import RunRecords
from chapmk.state import State, UnitInputs


def _rules(tmp_path: Path, refs: dict[str, str]) -> tuple[DirtyRules, CanonView]:
    src = tmp_path / "src"
    src.mkdir()
    for name in ("a", "b", "c"):
        (src / f"{name}.tex").write_text(f"\\chapter{{{name}}}")
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n"
        "\\include{a}\n\\include{b}\n\\include{c}\n\\end{document}\n"
    )
    analysis = analyse(Config(main=src / "main.tex"))
    state = State(1700000000, {}, "stamp", ["a", "b", "c"], {})
    for seg in analysis.unit_segments:
        state.units[seg] = UnitInputs({0: 1}, {}, None, True)
    rules = DirtyRules(analysis, state, lambda seg: TokenScan([refs.get(seg, "")]), print)
    view = CanonView([], {}, {"L:fig": "h1"}, "lists")
    state.glue_inputs = rules.glue_inputs(view)
    return rules, view


def test_nothing_changed(tmp_path: Path) -> None:
    rules, view = _rules(tmp_path, {})
    recs = RunRecords(base={0: 1}, entries={"U1": {}, "U2": {}, "U3": {}})
    assert rules.after_run(recs, {"U1"}, view, view) == ({}, None)


def test_entry_change_makes_the_later_units_a_tail_run(tmp_path: Path) -> None:
    rules, view = _rules(tmp_path, {})
    recs = RunRecords(base={0: 1}, entries={"U1": {}, "U2": {0: 5}, "U3": {0: 5}})
    dirty, glue = rules.after_run(recs, {"U1"}, view, view)
    assert dirty["U2"][0].startswith("entry state changed (\\count0")
    assert "after b, whose entry state changed (tail run)" in dirty["U3"]
    assert "U1" not in dirty and glue is None


def test_changed_import(tmp_path: Path) -> None:
    rules, view = _rules(tmp_path, {"U3": "see \\ref{fig}"})
    rules.state.units["U3"].imports["L:fig"] = "h0"
    recs = RunRecords(base={0: 1}, entries={"U1": {}, "U2": {}, "U3": {}})
    dirty, _ = rules.after_run(recs, {"U1"}, view, view)
    assert dirty == {"U3": ["imports changed (L:fig)"]}


def test_glue_inputs_and_unstable_self_data(tmp_path: Path) -> None:
    rules, view = _rules(tmp_path, {})
    rules.state.units["U1"].self_stable = False
    other = CanonView([], {}, {"L:fig": "h1"}, "other lists")
    recs = RunRecords(base={0: 1}, entries={"U1": {}, "U2": {}, "U3": {}})
    dirty, glue = rules.after_run(recs, {"U1"}, view, other)
    assert dirty == {"U1": ["self data unstable (rerun)"]}
    assert glue == "glue inputs changed (lists)"
