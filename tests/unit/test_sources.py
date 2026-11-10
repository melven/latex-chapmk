"""Unit tests for sources.py: owners of anchors used by later segments (S19)."""

from types import SimpleNamespace

from chapmk.segment import document_order, seg_index
from chapmk.sources import anchor_owner, anchor_owners
from chapmk.state import State


def _doc(n: int, groups: list[list[int]]) -> SimpleNamespace:
    includes = [SimpleNamespace(arg=f"c{k}") for k in range(1, n + 1)]
    return SimpleNamespace(
        segments=document_order(n),
        units=[SimpleNamespace(includes=tuple(includes[k - 1] for k in g)) for g in groups],
        include_of=lambda seg: includes[seg_index(seg) - 1],
    )


def _state(anchors: dict[str, bool], reads: dict[str, list[tuple[str, int]]]) -> State:
    """Committed segments ``anchors`` (with an ``H`` fact if true) and ``R`` facts ``reads``."""
    facts: dict[str, dict[str, list[tuple[str, ...]]]] = {
        seg: {"H": [()]} if sets else {} for seg, sets in anchors.items()
    }
    for seg, rs in reads.items():
        facts.setdefault(seg, {})["R"] = [(c, str(n)) for c, n in rs]
    return State(0, {}, "", [], {}, facts=facts)


def test_anchor_owner() -> None:
    a = _doc(3, [[1], [2], [3]])
    sets = {"G0": False, "U1": True, "G1": False, "U2": True, "G2": False, "U3": True}
    # glue after the last unit: its last anchor
    assert anchor_owner(a, _state(sets, {}), "G3") == "U3"  # type: ignore[arg-type]
    # a unit without anchors passes the one before it through
    assert anchor_owner(a, _state({**sets, "U3": False}, {}), "G3") == "U2"  # type: ignore[arg-type]
    # an anchor of the glue in between (compiled in every run), or none in the body
    assert anchor_owner(a, _state({**sets, "G2": True}, {}), "U3") is None  # type: ignore[arg-type]
    none = dict.fromkeys(sets, False)
    assert anchor_owner(a, _state(none, {}), "G3") is None  # type: ignore[arg-type]
    # a segment without a record yet counts as setting one
    assert anchor_owner(a, _state({}, {}), "G3") == "U3"  # type: ignore[arg-type]


def test_anchor_owner_in_the_same_compilation_unit() -> None:
    """A unit compiled with the reader needs nothing; the glue between them does (it is
    compiled also in runs that exclude both)."""
    a = _doc(3, [[1], [2, 3]])
    sets = {"G0": False, "U1": True, "G1": False, "U2": True, "G2": False, "U3": False}
    assert anchor_owner(a, _state(sets, {}), "U3") is None  # type: ignore[arg-type]
    assert anchor_owner(a, _state(sets, {}), "G2") == "U2"  # type: ignore[arg-type]
    owners = anchor_owners(
        a,  # type: ignore[arg-type]
        _state(sets, {"G2": [("label", 7)], "U3": [("addcontentsline", 1)], "G3": []}),
    )
    assert owners == {"U2": [("G2", "label", 7)]}
