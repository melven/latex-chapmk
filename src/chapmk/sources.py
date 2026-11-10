"""What the builder knows about the sources of each unit (design §6.8): token scans (imports,
list reads) and lint hits (global units, §6.8.4), cached per build; the persistent lint cache
(``canon/lint-cache.json``, only the entries a build used are kept); the global units
(§6.8.4: one table of rules, :data:`GLOBAL_RULES`), among them the units whose anchor a later
segment uses (S19)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from chapmk.analysis import Analysis
from chapmk.config import Config
from chapmk.deps import TokenScan, read_text
from chapmk.files import write_atomic
from chapmk.lint import LintHit, lint_files
from chapmk.logs import short_list
from chapmk.segment import is_glue
from chapmk.state import State

LINT_CACHE = "lint-cache.json"


class _UsedCache(dict[str, list[list[Any]]]):
    """A cache that looks up ``old`` entries and holds only the entries used or added (saved
    after the build, so it does not grow with every edit)."""

    def __init__(self, old: dict[str, list[list[Any]]]) -> None:
        super().__init__()
        self.old = old

    def __contains__(self, key: object) -> bool:
        return dict.__contains__(self, key) or key in self.old

    def __getitem__(self, key: str) -> list[list[Any]]:
        if not dict.__contains__(self, key):
            self[key] = self.old[key]
        return dict.__getitem__(self, key)


def load_lint_cache(canon_dir: Path) -> _UsedCache:
    """The persistent lint cache (linting all units is otherwise the largest Python cost of a
    typo build); unreadable: empty."""
    try:
        old = json.loads((canon_dir / LINT_CACHE).read_bytes())
    except (OSError, ValueError):
        old = {}
    return _UsedCache(old if isinstance(old, dict) else {})


def save_lint_cache(canon_dir: Path, cache: _UsedCache) -> None:
    write_atomic(canon_dir / LINT_CACHE, json.dumps(dict(cache)))


def anchor_owner(analysis: Analysis, state: State, reader: str) -> str | None:
    """S19: the unit whose anchor an ``\\addcontentsline`` or ``\\label`` of segment ``reader``
    used (``R`` records): the nearest earlier segment that sets an anchor (``H`` records; a
    segment without a record yet counts as setting one). None if that is a glue segment
    (compiled in every run) or a unit of the reader's own compilation unit (compiled with it),
    or if no earlier segment sets one (the anchor comes from before the body, e.g. hyperref's
    ``Doc-Start``)."""
    order = analysis.segments
    for seg in reversed(order[: order.index(reader)]):
        if seg in state.facts and not state.fact(seg, "H"):
            continue
        if is_glue(seg):
            return None
        if not is_glue(reader):
            own = next(u for u in analysis.units if analysis.include_of(reader) in u.includes)
            if analysis.include_of(seg) in own.includes:
                return None
        return seg
    return None


def anchor_owners(analysis: Analysis, state: State) -> dict[str, list[tuple[str, str, int]]]:
    """Per owner unit (:func:`anchor_owner`): the reads of its anchor as (reading segment,
    command, line), in document order."""
    owners: dict[str, list[tuple[str, str, int]]] = {}
    for reader in analysis.segments:
        reads = state.fact(reader, "R")
        owner = anchor_owner(analysis, state, reader) if reads else None
        if owner is not None:
            owners.setdefault(owner, []).extend((reader, c, int(n)) for c, n in reads)
    return owners


def _lint_rule(src: UnitSources, seg: str) -> str | None:
    hits = src.lint(seg)
    return f"lint: {short_list(sorted({h.command for h in hits}), 3)}" if hits else None


def _runtime_rule(src: UnitSources, seg: str) -> str | None:
    changed = [c for (c,) in src.state.fact(seg, "G")]
    return f"changes {', '.join(changed)} at run time" if changed else None


def _anchor_rule(src: UnitSources, seg: str) -> str | None:
    return "a later part uses its anchor" if seg in anchor_owners(src.a, src.state) else None


#: Why a unit is global (§6.8.4): it changes state that no checkpoint carries, so it is compiled
#: in every run, and when it becomes global, the later segments committed from runs without it
#: are compiled again (incremental). Each rule gives its reason or None: an A1 lint hit in its
#: sources, a change at run time (``G`` facts), its anchor used by a later segment (S19). A new
#: kind of global unit is one rule here.
GLOBAL_RULES: tuple[Callable[[UnitSources, str], str | None], ...] = (
    _lint_rule,
    _runtime_rule,
    _anchor_rule,
)


class UnitSources:
    """Token scans and lint hits of the sources attributed to each segment (``state``),
    computed on first use; :meth:`forget` drops them after a commit changed the attribution."""

    def __init__(
        self, analysis: Analysis, state: State, config: Config, lint_cache: _UsedCache
    ) -> None:
        self.a, self.state, self.config, self.lint_cache = analysis, state, config, lint_cache
        self._scans: dict[str, TokenScan] = {}
        self._lint: dict[str, list[LintHit]] = {}

    def _texts(self, seg: str) -> list[str]:
        texts = []
        for name in self.state.segment_files.get(seg, {}):
            text = read_text(self.a.source_dir / name)
            if text is not None:
                texts.append(text)
        return texts

    def scan(self, seg: str) -> TokenScan:
        """Token scan of a unit's attributed sources (``"glue"``: main file and glue files)."""
        if seg not in self._scans:
            if seg == "glue":
                texts = [read_text(self.a.main) or ""]
                for g in self.a.glue_segments:
                    texts += self._texts(g)
            else:
                texts = self._texts(seg)
            self._scans[seg] = TokenScan(texts)
        return self._scans[seg]

    def lint(self, seg: str) -> list[LintHit]:
        """A1 lint hits in the TeX sources attributed to a unit (§6.8.4)."""
        if seg not in self._lint:
            cfg = self.config
            self._lint[seg] = lint_files(
                self.a.source_dir,
                self.state.segment_files.get(seg, {}),
                cfg.lint_allow,
                cfg.lint_verbatim,
                cfg.lint_shortverb,
                self.lint_cache,
            )
        return self._lint[seg]

    def global_reasons(self, seg: str) -> list[str]:
        """Why ``seg`` is a global unit (:data:`GLOBAL_RULES`); empty if it is none."""
        return [r for rule in GLOBAL_RULES if (r := rule(self, seg)) is not None]

    def is_global(self, seg: str) -> bool:
        """Global unit (§6.8.4): any of :data:`GLOBAL_RULES` applies."""
        return any(rule(self, seg) is not None for rule in GLOBAL_RULES)

    def forget(self, segs: Iterable[str]) -> None:
        """Drop the scans and lint hits of ``segs`` and the glue scan (sources re-attributed)."""
        for seg in segs:
            self._scans.pop(seg, None)
            self._lint.pop(seg, None)
        self._scans.pop("glue", None)
