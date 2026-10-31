"""Canonical state (PLAN §6.6): what the last successful build consists of, persisted as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastinc.errors import FastincError

STATE_VERSION = 1
STATE_FILE = "state.json"


@dataclass(frozen=True)
class SegmentArtifact:
    """Where a segment's output lives: run directory name and 0-based page indices in its PDF."""

    run: str
    pages: tuple[int, ...]


@dataclass
class State:
    """Persistent state of the canonical build in ``<build>/canon``.

    ``epoch`` is the SOURCE_DATE_EPOCH of all runs of this state (N4): reused pages and new
    runs must agree on dates. ``segment_files`` maps segment ids to {source path: sha256} of
    the files attributed to them; ``global_files`` are source files read by no particular
    segment (and ``.bib`` data sources); a change of these forces a cold build.
    """

    epoch: int
    fingerprints: dict[str, str]
    format_stamp: str
    includes: list[str]
    segments: dict[str, SegmentArtifact]
    segment_files: dict[str, dict[str, str]] = field(default_factory=dict)
    global_files: dict[str, str] = field(default_factory=dict)
    next_run: int = 1
    version: int = STATE_VERSION

    def run_names(self) -> set[str]:
        """Run directories referenced by the state (others can be garbage-collected)."""
        return {art.run for art in self.segments.values()}

    def new_run_name(self) -> str:
        name = f"r{self.next_run}"
        self.next_run += 1
        return name


def save_state(state: State, canon_dir: Path) -> None:
    """Write ``state.json`` atomically."""
    canon_dir.mkdir(parents=True, exist_ok=True)
    data = asdict(state)
    data["segments"] = {
        k: {"run": v.run, "pages": list(v.pages)} for k, v in state.segments.items()
    }
    tmp = canon_dir / f".{STATE_FILE}.tmp"
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(canon_dir / STATE_FILE)


def load_state(canon_dir: Path) -> State | None:
    """The persisted state, or ``None`` if there is none or it is unusable (cold build)."""
    path = canon_dir / STATE_FILE
    if not path.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != STATE_VERSION:
            return None
        segments = {
            k: SegmentArtifact(v["run"], tuple(v["pages"])) for k, v in data["segments"].items()
        }
        return State(
            epoch=int(data["epoch"]),
            fingerprints=dict(data["fingerprints"]),
            format_stamp=str(data["format_stamp"]),
            includes=list(data["includes"]),
            segments=segments,
            segment_files={k: dict(v) for k, v in data["segment_files"].items()},
            global_files=dict(data["global_files"]),
            next_run=int(data["next_run"]),
        )
    except (ValueError, KeyError, TypeError) as err:
        raise FastincError(f"{path}: corrupt state ({err}); run 'fastinc clean'") from err
