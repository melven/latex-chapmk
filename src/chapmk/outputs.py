"""Published outputs of the incremental builder (PLAN §6.11 to §6.13): merged PDF, merged SyncTeX
file, concatenated log, and the log of a failed run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from chapmk.analysis import Analysis
from chapmk.aux import parse_bookmark, read_lines, segment_slices
from chapmk.canon import segments
from chapmk.errors import FallbackError, TexError
from chapmk.files import digest, write_atomic
from chapmk.layout import Layout
from chapmk.logs import map_paths
from chapmk.publish import publish, text_writer
from chapmk.records import RunRecords, read_run_records
from chapmk.runner import RUN_MAIN
from chapmk.state import State
from chapmk.synctex import SyncTexError
from chapmk.synctex import merge as merge_synctex
from chapmk.texdist import TexDistribution
from chapmk.timing import Timings

if TYPE_CHECKING:
    from chapmk.merge_pdf import OutlineEntry, PageSource

PUBLISHED_FILE = "published.json"
_OUTPUTS = (".pdf", ".synctex.gz", ".log")


class MergeFailedError(FallbackError):
    """The PDF or SyncTeX merge failed (falls back to full mode, §6.14)."""


def map_run_paths(analysis: Analysis, layout: Layout, run_dir: Path, text: str) -> str:
    """Map run-directory and shadow paths in ``text`` to the user's paths (§6.13)."""
    mapping = [
        (str(run_dir / RUN_MAIN), str(analysis.main)),
        *layout.path_map(),
        (RUN_MAIN, analysis.main.name),
    ]
    return map_paths(text, mapping)


def failed_run(analysis: Analysis, layout: Layout, run_dir: Path, err: TexError) -> TexError:
    """Publish the failing run's log (paths mapped) and point the error at it (§6.13)."""
    log = run_dir / f"{analysis.jobname}.log"
    text = log.read_text(errors="replace") if log.is_file() else ""
    err.log = publish(
        text_writer(map_run_paths(analysis, layout, run_dir, text)), layout.output(".log")
    )
    return err


def publish_state(
    analysis: Analysis,
    layout: Layout,
    state: State,
    timings: Timings | None = None,
    *,
    dist: TexDistribution,
) -> Path:
    """Merge the canonical segments into the published PDF, SyncTeX file and log. The run
    main maps to the user's main file in the form the distribution records for an input in
    the working directory (as a full build of the main file would: S10, S11)."""
    from chapmk.merge_pdf import MergeError, OutlineEntry, PageSource, merge_pdf  # pikepdf

    t = timings or Timings()
    job = analysis.jobname
    runs: dict[str, RunRecords] = {}
    slices: dict[str, dict[str, list[str]]] = {}

    def records(run: str) -> RunRecords:
        if run not in runs:
            run_dir = layout.runs_dir / run
            runs[run] = read_run_records(run_dir, analysis)
            slices[run] = segment_slices(read_lines(run_dir / f"{job}.aux"))
        return runs[run]

    pages: list[PageSource] = []
    outline: list[OutlineEntry] = []
    syn: list[tuple[Path, int]] = []
    for seg in segments(analysis):
        art = state.segments[seg]
        recs = records(art.run)
        run_dir = layout.runs_dir / art.run
        by_index = {p.index: p for p in recs.pages}
        for i in art.pages:
            if i not in by_index:
                raise MergeFailedError(f"page {i} of run {art.run} has no page record")
            pages.append(
                PageSource(run_dir / f"{job}.pdf", i, by_index[i].value, by_index[i].label)
            )
            syn.append((run_dir / f"{job}.synctex.gz", i))
        for line in slices[art.run].get(seg, []):
            bkm = parse_bookmark(line)
            if bkm is not None:
                level = recs.bookmark_levels.get(bkm.id, 0)
                outline.append(OutlineEntry(level, bkm.open, bkm.dest, bkm.title))
    first_run = layout.runs_dir / state.segments["G0"].run

    def write_pdf(tmp: Path) -> None:
        try:
            merge_pdf(pages, outline, first_run / f"{job}.pdf", tmp)
        except MergeError as err:
            raise MergeFailedError(f"PDF merge: {err}") from err

    pdf = publish(write_pdf, layout.output(".pdf"))
    t.lap("merge_pdf")
    main_name = dist.synctex_input(analysis.source_dir, analysis.main.name)

    prefixes = [(old + "/", new) for old, new in layout.path_map()]

    def map_path(path: str) -> str:
        if Path(path).name == RUN_MAIN:
            return main_name
        for old, new in prefixes:
            if path.startswith(old):
                return new + path[len(old) - 1 :]
        return path

    try:
        publish(lambda tmp: merge_synctex(syn, map_path, tmp), layout.output(".synctex.gz"))
    except SyncTexError as err:
        raise MergeFailedError(f"SyncTeX merge: {err}") from err
    t.lap("merge_synctex")
    texts = []
    for run in sorted(state.run_names(), key=lambda r: int(r[1:])):
        log = layout.runs_dir / run / f"{job}.log"
        texts.append(
            f"%%% chapmk: log of run {run}\n"
            + map_run_paths(analysis, layout, log.parent, log.read_text(errors="replace"))
        )
    publish(text_writer("\n".join(texts)), layout.output(".log"))
    t.lap("log")
    return pdf


def _published_stamp(layout: Layout) -> dict[str, object]:
    canon_state = layout.canon_dir / "state.json"
    outputs: dict[str, list[int] | None] = {}
    for suffix in _OUTPUTS:
        path = layout.output(suffix)
        st = path.stat() if path.is_file() else None
        outputs[str(path)] = [st.st_size, st.st_mtime_ns] if st else None
    return {"state": digest(canon_state) if canon_state.is_file() else "", "outputs": outputs}


def is_published(layout: Layout) -> bool:
    """Whether the published outputs are those of the current canonical state: the state did
    not change since the last publish and the outputs (size, mtime) were not touched (e.g. by
    a plain latexmk run in the same directory)."""
    marker = layout.canon_dir / PUBLISHED_FILE
    try:
        return bool(json.loads(marker.read_text()) == _published_stamp(layout))
    except (OSError, ValueError):
        return False


def mark_published(layout: Layout) -> None:
    write_atomic(layout.canon_dir / PUBLISHED_FILE, json.dumps(_published_stamp(layout)))
