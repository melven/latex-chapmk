"""Published outputs of the incremental builder (PLAN §6.11 to §6.13): merged PDF, merged SyncTeX
file, concatenated log, and the log of a failed run."""

from __future__ import annotations

from pathlib import Path

from fastinc.analysis import Analysis
from fastinc.aux import parse_bookmark, read_lines, segment_slices
from fastinc.canon import segments
from fastinc.errors import FastincError, TexError
from fastinc.layout import Layout
from fastinc.logs import map_paths
from fastinc.merge_pdf import MergeError, OutlineEntry, PageSource, merge_pdf
from fastinc.publish import publish, text_writer
from fastinc.records import RunRecords, read_run_records
from fastinc.runner import RUN_MAIN
from fastinc.state import State
from fastinc.synctex import SyncTexError
from fastinc.synctex import merge as merge_synctex
from fastinc.timing import Timings


class MergeFailedError(FastincError):
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
    analysis: Analysis, layout: Layout, state: State, timings: Timings | None = None
) -> Path:
    """Merge the canonical segments into the published PDF, SyncTeX file and log."""
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
    main_name = f"{analysis.source_dir}/./{analysis.main.name}"

    def map_path(path: str) -> str:
        if Path(path).name == RUN_MAIN:
            return main_name
        for old, new in layout.path_map():
            if path.startswith(old + "/"):
                return new + path[len(old) :]
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
            f"%%% fastinc: log of run {run}\n"
            + map_run_paths(analysis, layout, log.parent, log.read_text(errors="replace"))
        )
    publish(text_writer("\n".join(texts)), layout.output(".log"))
    t.lap("log")
    return pdf
