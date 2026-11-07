"""What the builder knows about the sources of each unit (design §6.8): token scans (imports,
list reads) and lint hits (global units, §6.8.4), cached per build; the persistent lint cache
(``canon/lint-cache.json``, only the entries a build used are kept)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from chapmk.analysis import Analysis
from chapmk.config import Config
from chapmk.deps import TokenScan, read_text
from chapmk.files import write_atomic
from chapmk.lint import LintHit, lint_files
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

    def is_global(self, seg: str) -> bool:
        """Global unit (§6.8.4): a lint hit, or state it changed at run time (``G`` records)."""
        return seg in self.state.runtime_global or bool(self.lint(seg))

    def forget(self, segs: Iterable[str]) -> None:
        """Drop the scans and lint hits of ``segs`` and the glue scan (sources re-attributed)."""
        for seg in segs:
            self._scans.pop(seg, None)
            self._lint.pop(seg, None)
        self._scans.pop("glue", None)
