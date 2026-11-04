"""Scheduling of the fixpoint loop (design §6.9.2, §6.9.3): which compilation units a batch
compiles, how they are grouped into parallel runs, the predicted start states of the runs
and the verification of the predictions afterwards."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from chapmk.analysis import Analysis
from chapmk.facts import UNIT_HEADINGS
from chapmk.logs import short_list
from chapmk.predict import SegmentVectors, Vector, modified, normalized, partition, predict
from chapmk.records import RunRecords
from chapmk.segment import seg_index, unit_id
from chapmk.state import State


class Schedule:
    """Planning state of one build: compilation-unit groups, consecutive mispredictions,
    the entries observed in the latest run and the vectors the last prediction used.
    ``is_global`` tells whether a unit is global (lint, §6.8.4); ``jobs`` is ``-j``."""

    def __init__(
        self,
        analysis: Analysis,
        state: State,
        is_global: Callable[[str], bool],
        jobs: int,
        say: Callable[[str], None] = lambda _m: None,
    ) -> None:
        self.a, self.state, self.is_global, self.jobs, self.say = (
            analysis,
            state,
            is_global,
            jobs,
            say,
        )
        self.units = analysis.unit_segments
        index = {inc.arg: k for k, inc in enumerate(analysis.includes, start=1)}
        self.group: dict[int, list[int]] = {}
        for unit in analysis.units:
            ks = [index[inc.arg] for inc in unit.includes]
            for k in ks:
                self.group[k] = ks
        self.register_names: dict[int, str] = {}  # for messages, from the logs
        self.last_entries: dict[str, Vector] = {}  # observed in the latest run
        self.mispredicted: dict[str, int] = {}  # consecutive mispredictions per unit
        self.state_before: dict[str, SegmentVectors] = {}  # vectors the prediction used
        self.odd: frozenset[str] = frozenset()  # units starting on an odd page

    def plan(self, dirty: Mapping[str, list[str]]) -> tuple[list[int] | None, dict[str, list[str]]]:
        """Include indices to compile (None = all) and the reasons per unit segment.

        Whole compilation units are compiled. A *global* unit (lint, §6.8.4) changes state
        that checkpoints do not restore, so it is part of every run; when it is dirty itself,
        all later units are compiled with it (they see its new state only in the same run).
        """
        reasons = {seg: list(r) for seg, r in dirty.items()}
        ks: set[int] = set()
        for seg in dirty:
            ks.update(self.group[seg_index(seg)])
        n = len(self.units)
        own = [k for k in sorted(ks) if self.is_global(unit_id(k))]
        if own:
            arg = self.a.includes[own[0] - 1].arg
            for k in range(own[0] + 1, n + 1):
                if k not in ks:
                    reasons[unit_id(k)] = [f"follows the global unit {arg} (lint)"]
                    ks.add(k)
        for k in range(1, n + 1):
            if k not in ks and self.is_global(unit_id(k)):
                reasons[unit_id(k)] = ["global unit (lint): compiled in every run for its state"]
                ks.update(self.group[k])
        return (None if len(ks) == n else sorted(ks)), reasons

    def groups(self, selection: list[int] | None) -> list[list[int] | None]:
        """Runs of one iteration: contiguous groups of the selected compilation units,
        balanced by page count, at most ``jobs`` (§6.9.2). One run (the tail run) if
        ``jobs`` is 1, a global unit exists (it would be compiled in every run), a unit has
        no vectors yet, or a unit of the zone was mispredicted twice in a row (§6.9.3 item 6).
        """
        ks = list(range(1, len(self.units) + 1)) if selection is None else selection
        jobs = self.jobs
        atoms: list[list[int]] = []
        for k in ks:
            if atoms and self.group[k] is self.group[atoms[-1][0]]:
                atoms[-1].append(k)
            else:
                atoms.append([k])
        single = (
            jobs <= 1
            or len(atoms) <= 1
            or any(self.is_global(u) for u in self.units)
            or any(s not in self.state.vectors for s in self.a.segments[2 * ks[0] - 1 :])
            or any(self.mispredicted.get(unit_id(k), 0) >= 2 for k in ks)
        )
        if single:
            return [selection]
        weights = [
            float(sum(max(1, len(self.state.segments[unit_id(k)].pages)) for k in atom))
            for atom in atoms
        ]
        return [[k for i in part for k in atoms[i]] for part in partition(weights, jobs)]

    def predictions(
        self, groups: list[list[int]], layout: Mapping[str, int]
    ) -> tuple[
        dict[str, tuple[Vector, Vector]], dict[int, dict[str, tuple[Vector, frozenset[int]]]]
    ]:
        """Predicted (entry, exit) per segment from the first unit of the batch on, and per
        run index the checkpoints to write into its excluded units: predicted exit and the
        registers the unit modifies (only those are restored)."""
        first = unit_id(groups[0][0])
        observed = self.last_entries.get(first)
        entry = observed if observed is not None else self.state.vectors[first].entry
        default = bool(layout.get("twoside") and layout.get("openright"))
        # per unit as recorded at its start (a local open=any counts), else the document's
        odd = frozenset(
            unit_id(k)
            for k, inc in enumerate(self.a.includes, start=1)
            if inc.heading in UNIT_HEADINGS and self.state.openright.get(unit_id(k), default)
        )
        self.odd = odd
        pred = predict(self.a.segments, self.state.vectors, first, entry, odd)
        rewrites: dict[int, dict[str, tuple[Vector, frozenset[int]]]] = {}
        for j, group in enumerate(groups):
            out: dict[str, tuple[Vector, frozenset[int]]] = {}
            for k in range(groups[0][0], group[0]):
                seg = unit_id(k)
                out[seg] = (pred[seg][1], modified(self.state.vectors[seg]))
            rewrites[j] = out
        return pred, rewrites

    def verify(
        self,
        groups: list[list[int] | None],
        all_recs: list[RunRecords],
        pred: dict[str, tuple[Vector, Vector]],
        dirty: dict[str, list[str]],
        glue: str | None,
    ) -> tuple[dict[str, list[str]], str | None]:
        """§6.9.3 item 5: the exits of units whose predicted checkpoint later runs used must
        equal the prediction. At the first mismatch the glue is invalid (its pages come from
        the last run) and the later units whose start entry changes under the corrected
        prediction are dirty again, with all units after them."""
        dirty = {seg: list(r) for seg, r in dirty.items()}
        real = [g for g in groups if g is not None]
        for j, (group, recs) in enumerate(zip(real[:-1], all_recs[:-1], strict=True)):
            for k in group:
                seg = unit_id(k)
                actual = normalized(recs.checkpoints.get(seg, {}))
                entry = recs.entry_state(seg)
                keep = modified(self.state_before[seg])
                # registers the unit modifies match the predicted exit; all others must still
                # pass through (exit = entry)
                regs = sorted(
                    r
                    for r in actual.keys() | pred[seg][1].keys() | entry.keys()
                    if (
                        actual.get(r, 0) != pred[seg][1].get(r, 0)
                        if r in keep
                        else actual.get(r, 0) != entry.get(r, 0)
                    )
                )
                if not regs:
                    self.mispredicted.pop(seg, None)
                    continue
                self.mispredicted[seg] = self.mispredicted.get(seg, 0) + 1
                names = [self.register_names.get(r, f"\\count{r}") for r in regs]
                arg = self.a.includes[k - 1].arg
                reason = f"misprediction: exit of {arg} ({short_list(names)})"
                self.say(reason)
                # predict again from the actual exit: later runs were compiled with a wrong
                # entry only if the corrected chain changes their start entries (a later
                # absolute assignment, e.g. \\mainmatter for the page, absorbs the error);
                # the glue pages (last run) are redone in any case
                order = self.a.segments
                nxt = order[order.index(seg) + 1]
                pred2 = predict(order, self.state_before, nxt, actual, self.odd)
                for later_group in real[j + 1 :]:
                    start = unit_id(later_group[0])
                    if pred2[start][0] != pred[start][0]:
                        for later in range(later_group[0], len(self.units) + 1):
                            dirty.setdefault(unit_id(later), []).append(reason)
                        break
                return dirty, reason
        return dirty, glue
