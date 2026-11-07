"""Dirty rules of the fixpoint loop (design §6.8, §6.9.1): which units must be compiled and
whether the glue is valid, at the start of a build and after each committed batch. Pure
apart from reading source digests: everything else comes from the canonical views, the run
records and the state."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Sequence

from chapmk.analysis import Analysis
from chapmk.auxfile import AGGREGATE, GLOBAL, command_name
from chapmk.canon import CanonView
from chapmk.deps import TokenScan, changed_imports, imports, short_hash
from chapmk.errors import FallbackError
from chapmk.files import changed_files
from chapmk.logs import short_list
from chapmk.records import RunRecords
from chapmk.segment import is_unit, position, seg_index
from chapmk.state import State


def _eqp_tag(key: str) -> str:
    """``\\expandafter\\gdef\\csname eqp@this@T\\endcsname`` -> ``T``."""
    m = re.search(r"eqp@[a-z]+@(.*?)\\endcsname", key)
    return m.group(1) if m else key


class DirtyRules:
    """The dirty rules for one build. ``scan`` gives the token scan of a segment's sources
    (``"glue"``: main file and glue files); ``warn`` reports a warning once.
    ``register_names`` and ``self_changes`` are filled by the builder (messages only)."""

    def __init__(
        self,
        analysis: Analysis,
        state: State,
        scan: Callable[[str], TokenScan],
        warn: Callable[[str], None],
    ) -> None:
        self.a, self.state, self.scan, self.warn = analysis, state, scan, warn
        self.units = analysis.unit_segments
        self.register_names: dict[int, str] = {}  # for messages, from the logs
        self.self_changes: dict[str, list[str]] = {}  # macros of changed self data

    def glue_inputs(self, view: CanonView) -> dict[str, str]:
        """Hashes of the glue's inputs (§6.8.2): derived files, imported values, aux data."""
        values = imports(self.scan("glue"), view.values)
        return {
            "lists": view.lists,
            "labels": short_hash(json.dumps(sorted(values.items()))),
            "aux": short_hash("\n".join(view.glue_data())),
        }

    def _glue_sources_changed(self) -> list[str]:
        return [
            name
            for g in self.a.glue_segments
            for name in changed_files(self.a.source_dir, self.state.segment_files.get(g, {}))
        ]

    def initial(self) -> tuple[dict[str, list[str]], str | None]:
        """Dirty units and glue at the start of an incremental build."""
        dirty = {seg: list(reasons) for seg, reasons in self.state.pending.items()}
        for seg in self.units:
            if seg not in self.state.units:
                dirty.setdefault(seg, []).append("never compiled")
                continue
            changed = changed_files(self.a.source_dir, self.state.segment_files.get(seg, {}))
            if changed:
                dirty.setdefault(seg, []).append(f"sources changed ({short_list(changed)})")
        glue = self.state.glue_pending
        changed = self._glue_sources_changed()
        if changed:
            glue = f"glue sources changed ({short_list(changed)})"
        return dirty, glue

    def after_run(
        self, recs: RunRecords, compiled: set[str], pre: CanonView, post: CanonView
    ) -> tuple[dict[str, list[str]], str | None]:
        """Dirty units and glue after committing a run (§6.9.1)."""
        dirty: dict[str, list[str]] = {}
        moved: list[int] = []  # indices of the units whose entry state changed

        def add(seg: str, reason: str) -> None:
            dirty.setdefault(seg, []).append(reason)

        g_pre, g_post = pre.of_class(GLOBAL), post.of_class(GLOBAL)
        if g_pre != g_post:
            names = _changed_names(g_pre, g_post)
            msg = f"unclassified aux data changed ({short_list(names)})"
            self.warn(f"{msg}: all units are recompiled; please report these macros")
            for seg in self.units:
                add(seg, msg)
        if set(pre.of_class(AGGREGATE)) != set(post.of_class(AGGREGATE)):
            for seg in self.units:
                add(seg, "aggregate aux data changed (e.g. KOMA autodot)")
        eqp_pre, eqp_post = pre.eqp(), post.eqp()
        tags = sorted({_eqp_tag(k) for k, v in eqp_post.items() if eqp_pre.get(k) != v})
        self._check_shared_tags(tags)
        if tags:
            # the units that use a changed tag (Q records); unknown owners: all compiled units
            owners = {
                seg for seg in self.units if set(tags) & set(self.state.eqp_tags.get(seg, ()))
            }
            known = {t for seg_tags in self.state.eqp_tags.values() for t in seg_tags}
            if not set(tags) <= known:
                owners |= compiled
            for seg in sorted(owners, key=position):
                add(seg, f"eqparbox widths changed ({short_list(tags)})")
        for seg in self.units:
            info = self.state.units.get(seg)
            if info is None:
                add(seg, "never compiled")
                continue
            if seg in compiled and not info.self_stable:
                names = self.self_changes.get(seg, [])
                add(seg, f"self data unstable ({short_list(names) if names else 'rerun'})")
            if seg not in compiled and seg in recs.entries:
                entry = recs.entry_state(seg)
                counter = self.a.include_of(seg).resets
                reset = recs.reset_registers(counter) if counter else set()
                regs = sorted(
                    r
                    for r in entry.keys() | info.entry.keys()
                    if r not in reset and entry.get(r) != info.entry.get(r)
                )
                if regs:
                    shown = [self.register_names.get(r, f"\\count{r}") for r in regs]
                    add(seg, f"entry state changed ({short_list(shown)})")
                    moved.append(seg_index(seg) - 1)
            keys = changed_imports(info.imports, self.scan(seg), post.values)
            if keys:
                add(seg, f"imports changed ({short_list(keys)})")
            if info.lists is not None and info.lists != post.lists_key(info.list_reads):
                add(seg, "list files changed")
            changed = changed_files(self.a.source_dir, self.state.segment_files.get(seg, {}))
            if changed:
                add(seg, f"sources changed ({short_list(changed)})")
        # tail run (§6.9.2, without prediction): recompiling a unit whose entry changed may
        # change its exit, so all later units are compiled with it, in one run
        if moved:
            first = self.a.includes[moved[0]].arg
            for seg in self.units[moved[0] + 1 :]:
                add(seg, f"after {first}, whose entry state changed (tail run)")
        glue = None
        now = self.glue_inputs(post)
        if now != self.state.glue_inputs:
            parts = [k for k, v in now.items() if self.state.glue_inputs.get(k) != v]
            glue = f"glue inputs changed ({', '.join(parts)})"
        changed = self._glue_sources_changed()
        if changed:
            glue = f"glue sources changed ({short_list(changed)})"
        return dirty, glue

    def _check_shared_tags(self, changed: Sequence[str]) -> None:
        """C13: eqparbox sets all boxes of a tag to the widest one, computed from the boxes
        of one run. A tag used in several segments whose width changed while these were
        last compiled in different runs can differ from a full build: full mode."""
        for tag in changed:
            owners = [
                seg
                for seg in self.a.segments
                if tag in self.state.eqp_tags.get(seg, ()) and seg in self.state.segments
            ]
            if len({self.state.segments[seg].run for seg in owners}) > 1:
                names = [self.a.include_of(s).arg if is_unit(s) else s for s in owners]
                raise FallbackError(
                    f"eqparbox tag {tag!r} is used in {', '.join(names)}: its width (the widest "
                    "box) changed, and a partial run sees only its own boxes (use the tag in one "
                    "chapter only, or one tag per chapter, to build incrementally)"
                )


def _changed_names(old: list[str], new: list[str]) -> list[str]:
    """Commands of the statements that differ between two statement lists: added or removed,
    also repeated statements (counted), else the reordered ones."""
    a, b = Counter(old), Counter(new)
    changed = set((a - b) | (b - a))
    if not changed:  # same statements in another order
        changed = {x for x, y in zip(old, new, strict=True) if x != y}
    return sorted({command_name(s) for s in changed})
