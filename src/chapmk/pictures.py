"""Picture cache (PLAN §6.17, S12): the user's TikZ externalize, redirected by chapmk-ini.sty.

TeX looks a figure up by its key in the picture directory. A missing figure is typeset inline
and a copy of its box is shipped as an extra page of the run's PDF; the driver splits these
pages into ``<key>.pdf`` plus ``<key>.dpth`` (depth, read by TikZ external's embedding) and
reruns the segment. Records (log lines, written by ``\\chapmk@picrec``)::

    chapmk-picture: x <key> <0-based PDF page> <depth> <segment>   exported
    chapmk-picture: u <key> <segment>                              figure used
    chapmk-picture: s <key> <picture code>                         code of an exported one
    chapmk-picture: f <key> <file>                                 file read while exporting

The key covers the code and the state at the picture. References inside the code (labels,
citations) are checked by the driver: an exported figure stores its code (``<key>.src``) and
the values of the keys it referenced and the digests of the source files it read
(``<key>.deps``: recorded ``\\input``/graphics files plus files named in the code, e.g.
pgfplots tables); :func:`stale_figures` finds figures whose references or files changed.
``inputs.json`` holds the stat signatures of the distribution files read by the runs that
exported into the cache; a change (package update) empties the cache (:func:`check_inputs`).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from chapmk.deps import TokenScan, changed_imports, imports
from chapmk.files import digest, read_log, write_atomic
from chapmk.shadow import changed_signatures
from chapmk.texdist import tex_path

#: driver parameters, read by chapmk-ini.sty at ``\begin{document}`` (run or output directory)
PICS_FILE = "chapmk-pics.tex"
_RECORD = re.compile(
    r"^chapmk-picture: (?:x (?P<xkey>[0-9A-F]{32}) (?P<page>\d+) (?P<depth>\S+) (?P<xseg>\S+)"
    r"|u (?P<ukey>[0-9A-F]{32}) (?P<useg>\S+))\s*$",
    re.MULTILINE,
)
_SOURCE = "chapmk-picture: s "
_FILE = re.compile(r"^chapmk-picture: f ([0-9A-F]{32}) (.+?)\s*$", re.MULTILINE)
#: distribution files of the exporting runs (C4)
INPUTS_FILE = "inputs.json"
#: TeX breaks log lines at ``max_print_line`` (texdist.deterministic_env)
_MAX_PRINT_LINE = 10000


@dataclass(frozen=True)
class PictureRecord:
    """One picture of a run: ``exported`` (with PDF page index and depth) or a used figure."""

    key: str
    segment: str
    exported: bool
    page: int = -1
    depth: str = ""
    source: str = ""  # picture code (exported pictures)
    files: tuple[str, ...] = ()  # files read while it was exported (as TeX recorded them)


def read_pictures(log: Path) -> list[PictureRecord]:
    """Picture records of a run's log, in order."""
    return parse_pictures(read_log(log)) if log.is_file() else []


def parse_pictures(text: str) -> list[PictureRecord]:
    """Picture records of a log's text, in order."""
    sources: dict[str, str] = {}
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(_SOURCE) and len(line) > len(_SOURCE) + 33:
            body = [line[len(_SOURCE) + 33 :]]
            j = i
            while len(lines[j]) >= _MAX_PRINT_LINE and j + 1 < len(lines):  # broken line
                j += 1
                body.append(lines[j])
            sources[line[len(_SOURCE) : len(_SOURCE) + 32]] = "".join(body)
    files: dict[str, list[str]] = {}
    for m in _FILE.finditer(text):
        files.setdefault(m.group(1), []).append(m.group(2))
    out = []
    for m in _RECORD.finditer(text):
        if m.group("xkey"):
            key = m.group("xkey")
            out.append(
                PictureRecord(
                    key,
                    m.group("xseg"),
                    True,
                    int(m.group("page")),
                    m.group("depth"),
                    sources.get(key, ""),
                    tuple(files.get(key, ())),
                )
            )
        else:
            out.append(PictureRecord(m.group("ukey"), m.group("useg"), False))
    return out


def export_figures(pdf: Path, records: Iterable[PictureRecord], fig_dir: Path) -> int:
    """Write ``<key>.pdf`` (the extra page) and ``<key>.dpth`` for each exported picture;
    returns the number written."""
    exported = [r for r in records if r.exported]
    if not exported:
        return 0
    import pikepdf  # lazy: only needed when pictures were exported

    fig_dir.mkdir(parents=True, exist_ok=True)
    with pikepdf.open(pdf) as src:
        for r in exported:
            out = pikepdf.new()
            out.pages.append(src.pages[r.page])
            tmp = fig_dir / f"{r.key}.{os.getpid()}.tmp.pdf"
            out.save(tmp, deterministic_id=True)
            write_atomic(fig_dir / f"{r.key}.dpth", f"{r.depth}\n")
            tmp.replace(fig_dir / f"{r.key}.pdf")
    return len(exported)


def driver_file(fig_dir: Path | None, cwd: Path, stamp: str, refs: Mapping[str, str]) -> str:
    """Content of :data:`PICS_FILE`: picture directory relative to the TeX working directory
    ``cwd`` (``None``: no cache, pictures are typeset inline), stamp and per-segment digests
    of the referenced label and citation values."""

    def define(name: str, value: str) -> str:
        return f"\\expandafter\\def\\csname {name}\\endcsname{{{value}}}%\n"

    picdir = "" if fig_dir is None else tex_path(Path(os.path.relpath(fig_dir, cwd))) + "/"
    text = define("chapmk@picdir", picdir) + define("chapmk@picstamp", stamp)
    for seg, value in sorted(refs.items()):
        text += define(f"chapmk@picrefs@{seg}", value)
    return text


def _source_name(recorded: str, source_dir: Path) -> str | None:
    """A file name as TeX recorded it, relative to the source directory, if it is a source."""
    name = recorded.strip().lstrip("/")
    name = name[2:] if name.startswith("./") else name
    return name if name and (source_dir / name).is_file() else None


def store_references(
    fig_dir: Path, rec: PictureRecord, values: Mapping[str, str], source_dir: Path
) -> None:
    """Store an exported picture's code, the values of the keys it references and the
    digests of the source files it read or names (tables, inputs, images)."""
    write_atomic(fig_dir / f"{rec.key}.src", rec.source)
    scan = TokenScan([rec.source])
    names = {_source_name(f, source_dir) for f in rec.files}
    names |= {_source_name(t, source_dir) for t in scan.tokens if "." in t or "/" in t}
    files = {n: digest(source_dir / n) for n in sorted(n for n in names if n)}
    data = {
        "deps": imports(scan, values),
        "tokens": sorted(scan.tokens),
        "text": scan.texts[0],
        "files": files,
    }
    write_atomic(fig_dir / f"{rec.key}.deps", json.dumps(data, sort_keys=True))


def stale_figures(
    fig_dir: Path, values: Mapping[str, str] | None, source_dir: Path | None = None
) -> list[str]:
    """Keys of figures whose code references a label or citation whose value changed (or
    that became defined or undefined) since the figure was exported (``values``; None: not
    checked, full mode has the references in the key), or one of whose files changed."""
    stale: list[str] = []
    if not fig_dir.is_dir():
        return stale
    for src in sorted(fig_dir.glob("*.src")):
        key = src.name[: -len(".src")]
        deps_file = fig_dir / f"{key}.deps"
        try:
            data = json.loads(deps_file.read_text(encoding="utf-8"))
            scan = TokenScan.stored(data["tokens"], data["text"])
            stored = data["deps"]
        except (OSError, ValueError, KeyError, TypeError):  # also an earlier format: stale
            stale.append(key)
            continue
        files = data.get("files", {}) if isinstance(data, dict) else {}
        if (values is not None and changed_imports(stored, scan, values)) or (
            source_dir is not None
            and any(
                not (source_dir / n).is_file() or digest(source_dir / n) != d
                for n, d in files.items()
            )
        ):
            stale.append(key)
    return stale


def record_inputs(fig_dir: Path, signatures: Mapping[str, str]) -> None:
    """Add the distribution files read by an exporting run (stat signatures) to the cache."""
    path = fig_dir / INPUTS_FILE
    try:
        old = json.loads(path.read_bytes())
    except (OSError, ValueError):
        old = {}
    data = {**(old if isinstance(old, dict) else {}), **signatures}
    if data != old:
        fig_dir.mkdir(parents=True, exist_ok=True)
        write_atomic(path, json.dumps(data, sort_keys=True))


def check_inputs(fig_dir: Path) -> bool:
    """Empty the cache if a distribution file read by an exporting run changed (or the
    record is unreadable): figures of old package versions are never embedded. True if
    emptied."""
    path = fig_dir / INPUTS_FILE
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_bytes())
        valid = isinstance(data, dict) and not changed_signatures(data)
    except (OSError, ValueError):
        valid = False
    if valid:
        return False
    for f in fig_dir.iterdir():
        if f.is_file():
            f.unlink()
    return True


def remove_figures(fig_dir: Path, keys: Iterable[str]) -> None:
    for key in keys:
        for suffix in (".pdf", ".dpth", ".src", ".deps"):
            (fig_dir / f"{key}{suffix}").unlink(missing_ok=True)


def collect_garbage(fig_dir: Path, keep: set[str]) -> None:
    """Remove figures whose key is not in ``keep``."""
    if not fig_dir.is_dir():
        return
    for path in fig_dir.iterdir():
        if path.is_file() and path.name != INPUTS_FILE and path.name.split(".", 1)[0] not in keep:
            path.unlink()
