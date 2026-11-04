"""Wall-time breakdown of a build (``--report``: ``timings``; design §8.4)."""

from __future__ import annotations

import time


class Timings:
    """Accumulates wall time per phase; :meth:`lap` books the time since the previous lap."""

    def __init__(self) -> None:
        self.phases: dict[str, float] = {}
        self._last = time.perf_counter()

    def lap(self, phase: str) -> None:
        now = time.perf_counter()
        self.phases[phase] = self.phases.get(phase, 0.0) + now - self._last
        self._last = now

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 3) for k, v in self.phases.items()}
