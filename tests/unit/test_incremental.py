"""Unit tests for incremental.py: run planning."""


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
