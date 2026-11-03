"""Acceptance comparison of two builds (PLAN §3.3): rasters, text, labels, outline, links, SyncTeX.

Library used by the acceptance tests and by ``chapmk check`` (M3). Needs poppler
(``pdftoppm``, ``pdftotext``) and the ``synctex`` command-line tool.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pikepdf

from chapmk.errors import ToolError
from chapmk.files import digest
from chapmk.proc import run
from chapmk.texsource import text_lines

DPI = 150
SYNCTEX_SAMPLES = 8
_SYNCTEX_KEYS = re.compile(r"^(Page|x|y|h|v|W|H|Input|Line|Column):")


@dataclass(frozen=True)
class Difference:
    """One §3.3 item that differs; ``detail`` shows the first differing element."""

    item: str
    detail: str


@dataclass
class Report:
    """Result of a comparison: differences and the number of compared elements per item."""

    differences: list[Difference] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.differences

    def compare(self, item: str, ref: Sequence[Any], got: Sequence[Any]) -> None:
        """Record ``item`` with ``len(ref)`` elements; a difference if the sequences differ."""
        self.counts[item] = len(ref)
        if list(ref) == list(got):
            return
        for i, (a, b) in enumerate(zip(ref, got, strict=False)):
            if a != b:
                self.differences.append(Difference(item, f"#{i}: reference {a!r} != {b!r}"))
                return
        self.differences.append(Difference(item, f"length {len(ref)} != {len(got)}"))

    def summary(self) -> str:
        lines = [f"{'FAIL' if self.differences else 'PASS'}"]
        lines += [f"  {item}: {n} compared" for item, n in self.counts.items()]
        lines += [f"  DIFFERS {d.item}: {d.detail}" for d in self.differences]
        return "\n".join(lines)


# --- PDF structure ---------------------------------------------------------------------------

Target = tuple[Any, ...]


def _resolve(pdf: pikepdf.Pdf, pages: dict[Any, int], dest: Any) -> Target:
    """Named or explicit destination → (page index, view type, rounded coordinates)."""
    if isinstance(dest, (pikepdf.String, str)):
        names = pdf.Root.get("/Names")
        tree = pikepdf.NameTree(names.Dests) if names is not None and "/Dests" in names else None
        value = tree.get(str(dest)) if tree is not None else None
        if value is None:
            return ("missing", str(dest))
        dest = value.D if isinstance(value, pikepdf.Dictionary) else value
    page = (
        pages.get(dest[0].objgen, -1) if isinstance(dest[0], pikepdf.Dictionary) else int(dest[0])
    )
    coords = tuple(None if x is None else round(float(x), 3) for x in list(dest)[2:])
    return (page, str(dest[1]), coords)


def _structure(path: Path) -> tuple[list[str], list[Target], list[Target]]:
    """Page labels, flattened outline and link annotations of a PDF."""
    with pikepdf.open(path) as pdf:
        pages = {p.objgen: i for i, p in enumerate(pdf.pages)}
        labels = [str(pikepdf.Page(p).label) for p in pdf.pages]
        outline: list[Target] = []

        def walk(item: Any, level: int) -> None:
            while item is not None:
                action = item.get("/A")
                if action is not None and "/D" in action:
                    target = _resolve(pdf, pages, action.D)
                elif "/Dest" in item:
                    target = _resolve(pdf, pages, item.Dest)
                else:
                    target = ("action", str(action))
                outline.append((level, str(item.Title), int(item.get("/Count", 0)), target))
                walk(item.get("/First"), level + 1)
                item = item.get("/Next")

        outlines = pdf.Root.get("/Outlines")
        walk(outlines.get("/First") if outlines is not None else None, 0)
        links: list[Target] = []
        for i, page in enumerate(pdf.pages):
            for annot in page.get("/Annots", []):
                if annot.get("/Subtype") != "/Link":
                    continue
                rect = tuple(round(float(x), 3) for x in annot.Rect)
                action = annot.get("/A")
                if action is not None and action.get("/S") == "/URI":
                    links.append((i, rect, "uri", str(action.URI)))
                elif action is not None and "/D" in action:
                    links.append((i, rect, _resolve(pdf, pages, action.D)))
                elif "/Dest" in annot:
                    links.append((i, rect, _resolve(pdf, pages, annot.Dest)))
                else:
                    links.append((i, rect, "action", str(action)))
    return labels, outline, links


def _page_count(pdf: Path) -> int:
    r = run(["pdfinfo", str(pdf)], cwd=pdf.parent, env=dict(os.environ))
    m = re.search(r"^Pages:\s+(\d+)", r.output, re.MULTILINE)
    if not r.ok or m is None:
        raise ToolError(f"pdfinfo failed on {pdf}: {r.output.strip()[-300:]}")
    return int(m.group(1))


def _rasters(pdf: Path, workdir: Path, dpi: int, chunk: int = 25) -> list[str]:
    """SHA-256 of each rendered page. Pages are rendered in chunks and deleted at once (an
    uncompressed page at 150 dpi has about 6.5 MB; the pgf manual has 1136 pages)."""
    pages = _page_count(pdf)
    digests: list[str] = []
    for first in range(1, pages + 1, chunk):
        last = min(pages, first + chunk - 1)
        r = run(
            [
                "pdftoppm",
                "-r",
                str(dpi),
                "-f",
                str(first),
                "-l",
                str(last),
                str(pdf),
                str(workdir / "p"),
            ],
            cwd=workdir,
            env=dict(os.environ),
        )
        files = sorted(workdir.glob("p-*.ppm"))
        if not r.ok or len(files) != last - first + 1:
            raise ToolError(
                f"pdftoppm failed on {pdf} pages {first}-{last}: {r.output.strip()[-300:]}"
            )
        for f in files:
            digests.append(digest(f))
            f.unlink()
    return digests


def _texts(pdf: Path, workdir: Path) -> list[str]:
    out = workdir / "text.txt"
    run(["pdftotext", "-layout", str(pdf), str(out)], cwd=workdir, env=dict(os.environ))
    pages = out.read_text(errors="replace").split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


#: programs ``chapmk check`` needs (poppler-utils; synctex from TeX Live)
CHECK_TOOLS = ("pdfinfo", "pdftoppm", "pdftotext", "synctex")


def check_tools() -> None:
    """Raise :class:`ToolError` naming the missing programs, before any build starts."""
    missing = [tool for tool in CHECK_TOOLS if shutil.which(tool) is None]
    if missing:
        raise ToolError(
            "chapmk check needs programs not found on PATH: "
            + ", ".join(missing)
            + " (poppler-utils; synctex comes with TeX Live)"
        )


def compare_pdfs(ref: Path, got: Path, *, dpi: int = DPI, report: Report | None = None) -> Report:
    """§3.3 items 1-3: page count, rasters, text per page, page labels, outline, links."""
    report = report or Report()
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        ra, ga = _rasters(ref, Path(t1), dpi), _rasters(got, Path(t2), dpi)
        report.compare("page count", [len(ra)], [len(ga)])
        report.compare("raster pages", ra, ga)
        report.compare("text pages", _texts(ref, Path(t1)), _texts(got, Path(t2)))
    (rl, ro, rk), (gl, go, gk) = _structure(ref), _structure(got)
    report.compare("page labels", rl, gl)
    report.compare("outline items", ro, go)
    report.compare("links", rk, gk)
    return report


# --- SyncTeX -----------------------------------------------------------------------------------


def _synctex(args: list[str], cwd: Path) -> list[str]:
    r = run(["synctex", *args], cwd=cwd, env=dict(os.environ))
    return [line for line in text_lines(r.output) if _SYNCTEX_KEYS.match(line)]


def _first(result: list[str], key: str) -> str:
    return next(line.split(":", 1)[1] for line in result if line.startswith(f"{key}:"))


def compare_synctex(
    ref_pdf: Path,
    got_pdf: Path,
    sources: Sequence[str],
    cwd: Path,
    *,
    samples: int = SYNCTEX_SAMPLES,
    report: Report | None = None,
) -> Report:
    """§3.3 item 4: ``synctex view`` at up to ``samples`` lines per source file (evenly spread
    over the lines that have records in the reference) and ``synctex edit`` at the resulting
    positions. ``sources`` are relative to ``cwd`` or absolute, in the form ``synctex view``
    matches for the distribution (:meth:`TexDistribution.synctex_query`). No record found for
    any source is a difference: the comparison would otherwise pass without comparing (S11)."""
    report = report or Report()
    ref_views: list[list[str]] = []
    got_views: list[list[str]] = []
    ref_edits: list[list[str]] = []
    got_edits: list[list[str]] = []
    for source in sources:
        n = len((cwd / source).read_text(errors="replace").split("\n"))
        step = max(1, n // (samples * 3))
        hits = 0
        for line in range(1, n + 1, step):
            a = _synctex(["view", "-i", f"{line}:1:{source}", "-o", str(ref_pdf)], cwd)
            if not a:
                continue
            b = _synctex(["view", "-i", f"{line}:1:{source}", "-o", str(got_pdf)], cwd)
            ref_views.append([f"{source}:{line}", *a])
            got_views.append([f"{source}:{line}", *b])
            page, x, y = _first(a, "Page"), _first(a, "x"), _first(a, "y")
            ref_edits.append(_synctex(["edit", "-o", f"{page}:{x}:{y}:{ref_pdf}"], cwd))
            got_edits.append(_synctex(["edit", "-o", f"{page}:{x}:{y}:{got_pdf}"], cwd))
            hits += 1
            if hits >= samples:
                break
    report.compare("synctex view", ref_views, got_views)
    report.compare("synctex edit", ref_edits, got_edits)
    if sources and not ref_views:
        report.differences.append(
            Difference("synctex view", "no records found in the reference for any source file")
        )
    return report
