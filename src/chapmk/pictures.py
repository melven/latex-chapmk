"""Picture cache (PLAN §6.17, S12): the user's TikZ externalize, redirected by chapmk-ini.sty.

TeX looks a figure up by its key in the picture directory. A missing figure is typeset inline
and a copy of its box is shipped as an extra page of the run's PDF; the driver splits these
pages into ``<key>.pdf`` plus ``<key>.dpth`` (depth, read by TikZ external's embedding) and
reruns the segment. Records (log lines, written by ``\\chapmk@picrec``)::

    chapmk-picture: x <key> <0-based PDF page> <depth> <segment>   exported
    chapmk-picture: u <key> <segment>                              figure used
    chapmk-picture: s <key> <picture code>                         code of an exported one

The key covers the code and the state at the picture. References inside the code (labels,
citations) are checked by the driver: an exported figure stores its code (``<key>.src``) and
the values of the keys it referenced (``<key>.deps``); :func:`stale_figures` finds figures
whose references changed.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from chapmk.deps import TokenScan, changed_imports, imports
from chapmk.texdist import tex_path

#: driver parameters, read by chapmk-ini.sty at ``\begin{document}`` (run or output directory)
PICS_FILE = "chapmk-pics.tex"
_RECORD = re.compile(
    r"^chapmk-picture: (?:x (?P<xkey>[0-9A-F]{32}) (?P<page>\d+) (?P<depth>\S+) (?P<xseg>\S+)"
    r"|u (?P<ukey>[0-9A-F]{32}) (?P<useg>\S+))\s*$",
    re.MULTILINE,
)
_SOURCE = "chapmk-picture: s "
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


def read_pictures(log: Path) -> list[PictureRecord]:
    """Picture records of a run's log, in order."""
    if not log.is_file():
        return []
    text = log.read_text(errors="replace")
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
            tmp = fig_dir / f"{r.key}.tmp.pdf"
            out.save(tmp, deterministic_id=True)
            (fig_dir / f"{r.key}.dpth").write_text(f"{r.depth}\n", encoding="ascii")
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
    for seg, digest in sorted(refs.items()):
        text += define(f"chapmk@picrefs@{seg}", digest)
    return text


def store_references(fig_dir: Path, rec: PictureRecord, values: Mapping[str, str]) -> None:
    """Store an exported picture's code and the values of the keys it references."""
    (fig_dir / f"{rec.key}.src").write_text(rec.source, encoding="utf-8", errors="surrogateescape")
    scan = TokenScan([rec.source])
    data = {"deps": imports(scan, values), "tokens": sorted(scan.tokens), "text": scan.texts[0]}
    (fig_dir / f"{rec.key}.deps").write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def stale_figures(fig_dir: Path, values: Mapping[str, str]) -> list[str]:
    """Keys of figures whose code references a label or citation whose value changed (or
    that became defined or undefined) since the figure was exported."""
    stale: list[str] = []
    if not fig_dir.is_dir():
        return stale
    for src in sorted(fig_dir.glob("*.src")):
        key = src.name[: -len(".src")]
        deps_file = fig_dir / f"{key}.deps"
        try:
            data = json.loads(deps_file.read_text(encoding="utf-8"))
            if "tokens" in data:
                scan = TokenScan.stored(data["tokens"], data["text"])
                stored = data["deps"]
            else:  # written by an earlier version: only the referenced values
                code = src.read_text(encoding="utf-8", errors="surrogateescape")
                scan, stored = TokenScan([code]), data
        except (OSError, ValueError, KeyError, TypeError):
            stale.append(key)
            continue
        if changed_imports(stored, scan, values):
            stale.append(key)
    return stale


def remove_figures(fig_dir: Path, keys: Iterable[str]) -> None:
    for key in keys:
        for suffix in (".pdf", ".dpth", ".src", ".deps"):
            (fig_dir / f"{key}{suffix}").unlink(missing_ok=True)


def collect_garbage(fig_dir: Path, keep: set[str]) -> None:
    """Remove figures whose key is not in ``keep``."""
    if not fig_dir.is_dir():
        return
    for path in fig_dir.iterdir():
        if path.is_file() and path.name.split(".", 1)[0] not in keep:
            path.unlink()
