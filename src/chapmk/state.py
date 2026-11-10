"""Canonical state (design §6.6): what the last successful build consists of, persisted as JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from chapmk.errors import ChapmkError
from chapmk.facts import DEFAULT_LIST_SUFFIXES
from chapmk.files import write_atomic
from chapmk.predict import SegmentVectors
from chapmk.records import Facts

STATE_VERSION = 9
STATE_FILE = "state.json"


@dataclass(frozen=True)
class SegmentArtifact:
    """Where a segment's output lives: run directory name and 0-based page indices in its PDF."""

    run: str
    pages: tuple[int, ...]


@dataclass
class UnitInputs:
    """What a unit was compiled with (§6.8.1), stored at commit: the observed entry vector,
    the values of its imported keys at compile start, the key of the derived list files it
    reads at compile start (None: it reads none) with their suffixes (``list_reads``; None:
    all), and whether its self data was stable."""

    entry: dict[int, int]
    imports: dict[str, str]
    lists: str | None
    self_stable: bool
    list_reads: list[str] | None = None


@dataclass
class State:
    """Persistent state of the canonical build in ``<build>/canon``.

    ``epoch`` is the SOURCE_DATE_EPOCH of all runs of this state (N4): reused pages and new
    runs must agree on dates. ``segment_files`` maps segment ids to {source path: sha256} of
    the files attributed to them; ``global_files`` are source files read by no particular
    segment (and ``.bib`` data sources); a change of these forces a cold build.

    ``units`` (§6.6, §6.9) holds the compile-time inputs per unit segment, ``citations``
    the ``.bcf`` citekey elements per segment and ``aggregates`` the end-of-document aggregate
    statements per segment (from the run that committed the segment). ``glue_inputs`` holds
    the hashes of the glue inputs (``lists``, ``labels``, ``aux``) the committed glue was
    compiled with. ``pending`` holds the dirty
    units with reasons and ``glue_pending`` why the glue is invalid, if the last build did not
    reach the fixpoint (e.g. a TeX error). ``vectors`` holds entry, exit and absolute set of
    each segment from its committing run (prediction, §6.9.3); ``eqp_tags`` the eqparbox tags
    each segment used in its committing run; ``facts`` the per-segment facts of the
    committing run (``records.SEGMENT_FACTS``: units from their run, glue from the last run;
    every committed segment has an entry). ``dist_files`` holds the stat signatures
    of the distribution files read by the format build and the runs (C4): a change (e.g. a
    ``tlmgr`` update) forces a cold build, so reused pages and new runs never mix package
    versions.
    """

    epoch: int
    fingerprints: dict[str, str]
    format_stamp: str
    includes: list[str]
    segments: dict[str, SegmentArtifact]
    segment_files: dict[str, dict[str, str]] = field(default_factory=dict)
    global_files: dict[str, str] = field(default_factory=dict)
    next_run: int = 1
    units: dict[str, UnitInputs] = field(default_factory=dict)
    citations: dict[str, list[str]] = field(default_factory=dict)
    aggregates: dict[str, list[str]] = field(default_factory=dict)
    glue_inputs: dict[str, str] = field(default_factory=dict)
    pending: dict[str, list[str]] = field(default_factory=dict)
    glue_pending: str | None = None
    vectors: dict[str, SegmentVectors] = field(default_factory=dict)
    eqp_tags: dict[str, list[str]] = field(default_factory=dict)
    pictures: dict[str, list[str]] = field(default_factory=dict)  # figure keys per segment
    facts: dict[str, Facts] = field(default_factory=dict)
    # list files of the document: the defaults plus those recorded (L records)
    list_suffixes: list[str] = field(default_factory=lambda: list(DEFAULT_LIST_SUFFIXES))
    dist_files: dict[str, str] = field(default_factory=dict)  # path -> "size:mtime_ns"
    version: int = STATE_VERSION

    def fact(self, segment: str, kind: str) -> list[tuple[str, ...]]:
        """The arguments of the committed ``segment``'s facts of ``kind`` (empty: none)."""
        return self.facts.get(segment, {}).get(kind, [])

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
    for info in data["units"].values():
        info["entry"] = {str(r): v for r, v in info["entry"].items()}
    data["vectors"] = {
        seg: {
            "entry": {str(r): x for r, x in v.entry.items()},
            "exit": {str(r): x for r, x in v.exit.items()},
            "absolute": sorted(v.absolute),
        }
        for seg, v in state.vectors.items()
    }
    write_atomic(canon_dir / STATE_FILE, json.dumps(data, indent=1, sort_keys=True))


class CorruptStateError(ChapmkError):
    """``state.json`` cannot be read (truncated, edited, ...): the builder starts cold (E7)."""


def load_state(canon_dir: Path) -> State | None:
    """The persisted state, or ``None`` if there is none or it has an older version (cold
    build). An unreadable state raises :class:`CorruptStateError`."""
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
            units={
                k: UnitInputs(
                    entry={int(r): int(v) for r, v in u["entry"].items()},
                    imports=dict(u["imports"]),
                    lists=u["lists"],
                    self_stable=bool(u["self_stable"]),
                    list_reads=None if u["list_reads"] is None else list(u["list_reads"]),
                )
                for k, u in data["units"].items()
            },
            citations={k: list(v) for k, v in data["citations"].items()},
            aggregates={k: list(v) for k, v in data["aggregates"].items()},
            glue_inputs={str(k): str(v) for k, v in data["glue_inputs"].items()},
            pending={k: list(v) for k, v in data["pending"].items()},
            glue_pending=data["glue_pending"],
            vectors={
                seg: SegmentVectors(
                    {int(r): int(x) for r, x in v["entry"].items()},
                    {int(r): int(x) for r, x in v["exit"].items()},
                    frozenset(int(r) for r in v["absolute"]),
                )
                for seg, v in data["vectors"].items()
            },
            eqp_tags={k: list(v) for k, v in data["eqp_tags"].items()},
            pictures={k: list(v) for k, v in data["pictures"].items()},
            facts={
                seg: {kind: [tuple(map(str, a)) for a in args] for kind, args in f.items()}
                for seg, f in data["facts"].items()
            },
            list_suffixes=list(data["list_suffixes"]),
            dist_files={str(k): str(v) for k, v in data["dist_files"].items()},
        )
    except (ValueError, KeyError, TypeError, AttributeError) as err:
        raise CorruptStateError(f"{path} is unreadable ({type(err).__name__}: {err})") from err
