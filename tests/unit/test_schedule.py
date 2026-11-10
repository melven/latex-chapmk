"""Unit tests for schedule.py: run planning."""

from types import SimpleNamespace

from chapmk.schedule import Schedule
from chapmk.segment import seg_index, unit_ids


def _planner(n: int, groups: list[list[int]], global_units: set[int]) -> Schedule:
    includes = [SimpleNamespace(arg=f"c{k}") for k in range(1, n + 1)]
    analysis = SimpleNamespace(
        includes=includes,
        units=[SimpleNamespace(includes=[includes[k - 1] for k in g]) for g in groups],
        unit_segments=unit_ids(n),
    )
    return Schedule(
        analysis,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        lambda seg: ["lint: \\x"] if seg_index(seg) in global_units else [],
        jobs=1,
    )


def test_plan_groups_and_global_units() -> None:
    fp = _planner(5, [[1], [2, 3], [4], [5]], set())
    assert fp.plan({"U3": ["x"]})[0] == [2, 3]
    assert fp.plan({})[0] == []  # glue only
    assert fp.plan({f"U{k}": ["x"] for k in range(1, 6)})[0] is None
    # a global unit is in every run; when dirty itself, all later units join
    fp = _planner(5, [[1], [2], [3], [4], [5]], {2})
    sel, reasons = fp.plan({"U4": ["sources changed"]})
    assert reasons["U2"] == ["global unit (lint: \\x): compiled in every run for its state"]
    assert sel == [2, 4]
    sel, reasons = fp.plan({"U2": ["sources changed"]})
    assert sel == [2, 3, 4, 5] and reasons["U5"] == ["follows the global unit c2 (lint: \\x)"]
    assert fp.plan({})[0] == [2]
