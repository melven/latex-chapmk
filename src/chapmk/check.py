"""Acceptance comparison of two builds (design §3.3): rasters, text, labels, outline, links,
SyncTeX.

Library used by the acceptance tests and by ``chapmk check``. Needs poppler
(``pdftoppm``, ``pdftotext``) and the ``synctex`` command-line tool.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pikepdf

from chapmk.errors import ToolError, ToolTimeoutError
from chapmk.files import digest, read_log
from chapmk.proc import run
from chapmk.synctex import parse as parse_synctex
from chapmk.texsource import text_lines

DPI = 150
#: lines per source file queried with the ``synctex`` tool (each call is a process start)
SYNCTEX_SAMPLES = 1
_SYNCTEX_KEYS = re.compile(r"^(Page|x|y|h|v|W|H|Input|Line|Column):")
#: seconds per ``synctex`` call (one takes milliseconds) and attempts: MiKTeX's synctex on
#: Windows rarely hangs at start-up, before it reads anything (1 in about 17,000 calls in CI,
#: no log line); the same deterministic query is repeated once
SYNCTEX_TIMEOUT = 60.0
SYNCTEX_ATTEMPTS = 2


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
    notes: list[str] = field(default_factory=list)  # tolerated, printed (not a failure)

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
        lines += [f"  NOTE {n}" for n in self.notes]
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


#: largest difference of a /Widths entry tolerated by the raster comparison (per 1000 em)
WIDTH_TOLERANCE = 0.11


def _base_font(font: Any) -> str:
    """BaseFont without the subset tag (``ABCDEF+``)."""
    name = str(font.get("/BaseFont", ""))[1:]
    return name[7:] if len(name) > 7 and name[6] == "+" else name


def ref_widths_copy(ref: Path, got: Path, out: Path) -> Path:
    """A copy of ``got`` whose ``/Widths`` entries take the value of ``ref`` (same font, same
    code) where the two differ by at most :data:`WIDTH_TOLERANCE`. pdfTeX shares one font
    object among all sizes of a TFM and rounds its widths (to 0.1 per 1000 em) from the size
    whose object it created first, which depends on the fonts a run used; viewers place the
    glyphs of a string by these widths, so a page can differ in a few antialiased pixels."""
    widths: dict[str, dict[int, set[float]]] = {}
    with pikepdf.open(ref) as doc:
        for obj in doc.objects:
            if isinstance(obj, pikepdf.Dictionary) and isinstance(
                obj.get("/Widths"), pikepdf.Array
            ):
                codes = widths.setdefault(_base_font(obj), {})
                first = int(obj.get("/FirstChar", 0))
                for i, w in enumerate(obj.Widths):
                    codes.setdefault(first + i, set()).add(float(w))
    with pikepdf.open(got) as doc:
        for obj in doc.objects:
            if not (
                isinstance(obj, pikepdf.Dictionary)
                and isinstance(obj.get("/Widths"), pikepdf.Array)
            ):
                continue
            codes = widths.get(_base_font(obj), {})
            first = int(obj.get("/FirstChar", 0))
            for i, w in enumerate(obj.Widths):
                own = float(w)
                near = min(codes.get(first + i, ()), key=lambda c: abs(c - own), default=own)
                if 0 < abs(near - own) <= WIDTH_TOLERANCE:
                    obj.Widths[i] = near
        doc.save(out)
    return out


def _rasters_with_ref_widths(
    ref: Path, got: Path, pages: Sequence[int], workdir: Path, dpi: int
) -> list[str]:
    """SHA-256 of the pages (0-based) of :func:`ref_widths_copy`, rendered one by one."""
    copy = ref_widths_copy(ref, got, workdir / "ref-widths.pdf")
    digests = []
    try:
        for i in pages:
            r = run(
                [
                    "pdftoppm",
                    "-r",
                    str(dpi),
                    "-f",
                    str(i + 1),
                    "-l",
                    str(i + 1),
                    str(copy),
                    str(workdir / "w"),
                ],
                cwd=workdir,
                env=dict(os.environ),
            )
            files = sorted(workdir.glob("w-*.ppm"))
            if not r.ok or len(files) != 1:
                raise ToolError(
                    f"pdftoppm failed on {copy} page {i + 1}: {r.output.strip()[-300:]}"
                )
            digests.append(digest(files[0]))
            files[0].unlink()
    finally:
        copy.unlink()
    return digests


def _texts(pdf: Path, workdir: Path) -> list[str]:
    out = workdir / "text.txt"
    r = run(["pdftotext", "-layout", str(pdf), str(out)], cwd=workdir, env=dict(os.environ))
    if not r.ok or not out.is_file():
        raise ToolError(f"pdftotext failed on {pdf}: {r.output.strip()[-300:]}")
    pages = read_log(out).split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def box_metrics_copy(pdf: Path, out: Path) -> Path:
    """A copy of ``pdf`` whose font descriptors all take Ascent and CapHeight from the top of
    the FontBBox, Descent from its bottom, and have no XHeight. pdfTeX writes these metrics
    from the TFM of one instance of a font, which depends on the fonts a run used (merged runs
    differ); they change only the boxes of text extraction, never the rendering (glyphs and
    widths come from the font program and ``/Widths``)."""
    with pikepdf.open(pdf) as doc:
        for obj in doc.objects:
            if not isinstance(obj, pikepdf.Dictionary):
                continue
            bbox = obj.get("/FontBBox")
            if obj.get("/Type") == pikepdf.Name.FontDescriptor and isinstance(bbox, pikepdf.Array):
                obj.Ascent, obj.CapHeight, obj.Descent = bbox[3], bbox[3], bbox[1]
                if "/XHeight" in obj:
                    del obj["/XHeight"]
        doc.save(out)
    return out


def _texts_with_box_metrics(pdf: Path, workdir: Path) -> list[str]:
    """``_texts`` of :func:`box_metrics_copy`."""
    copy = box_metrics_copy(pdf, workdir / "box-metrics.pdf")
    try:
        return _texts(copy, workdir)
    finally:
        copy.unlink()


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
        pages = [i for i, (a, b) in enumerate(zip(ra, ga, strict=False)) if a != b]
        if (
            len(ra) == len(ga)
            and pages
            and _rasters_with_ref_widths(ref, got, pages, Path(t2), dpi) == [ra[i] for i in pages]
        ):
            report.counts["raster pages"] = len(ra)
            report.notes.append(
                f"raster pages: {len(pages)} page(s) equal up to /Widths rounding (at most "
                f"{WIDTH_TOLERANCE} per 1000 em: pdfTeX rounds them from the size of a font "
                "it used first; glyph positions differ by about 0.001pt)"
            )
        else:
            report.compare("raster pages", ra, ga)
        rt, gt = _texts(ref, Path(t1)), _texts(got, Path(t2))
        if rt != gt and _texts_with_box_metrics(ref, Path(t1)) == _texts_with_box_metrics(
            got, Path(t2)
        ):
            report.counts["text pages"] = len(rt)
            report.notes.append(
                "text pages: equal up to font descriptor metrics (Ascent, CapHeight, Descent, "
                "XHeight: pdfTeX takes them from one instance of a font; not visible, only "
                "text extraction boxes)"
            )
        else:
            report.compare("text pages", rt, gt)
    (rl, ro, rk), (gl, go, gk) = _structure(ref), _structure(got)
    report.compare("page labels", rl, gl)
    report.compare("outline items", ro, go)
    report.compare("links", rk, gk)
    (ri, rc), (gi, gc) = _document(ref), _document(got)
    report.compare("document info", ri, gi)
    report.compare("catalog entries", rc, gc)
    return report


#: catalog entries compared elsewhere (pages, outline, labels, destinations) or not merged
_CATALOG_SKIP = {"/Type", "/Pages", "/Outlines", "/PageLabels", "/Names", "/Dests"}


def _plain(obj: Any, pages: dict[Any, int], depth: int = 0) -> Any:
    """A comparable form of a PDF object: page references as page indices, streams as
    digests of their data."""
    if depth > 20:
        return "..."
    if isinstance(obj, pikepdf.Dictionary) and obj.is_indirect and obj.objgen in pages:
        return ("page", pages[obj.objgen])
    if isinstance(obj, pikepdf.Stream):
        return ("stream", hashlib.sha256(obj.read_bytes()).hexdigest())
    if isinstance(obj, pikepdf.Dictionary):
        return tuple(sorted((str(k), _plain(v, pages, depth + 1)) for k, v in obj.items()))
    if isinstance(obj, pikepdf.Array):
        return tuple(_plain(v, pages, depth + 1) for v in obj)
    return str(obj)


def _document(path: Path) -> tuple[list[Any], list[Any]]:
    """Document info and catalog entries (§3.3 item 3; S13: \\pdfinfo and \\pdfcatalog)."""
    with pikepdf.open(path) as pdf:
        pages = {p.objgen: i for i, p in enumerate(pdf.pages)}
        info = sorted((str(k), _plain(v, pages)) for k, v in pdf.docinfo.items())
        catalog = sorted(
            (str(k), _plain(v, pages)) for k, v in pdf.Root.items() if str(k) not in _CATALOG_SKIP
        )
    return info, catalog


# --- SyncTeX -----------------------------------------------------------------------------------


def _synctex(args: list[str], cwd: Path, timeout: float = SYNCTEX_TIMEOUT) -> list[str]:
    """The result lines of one ``synctex`` call; a hanging call is killed and repeated
    (:data:`SYNCTEX_ATTEMPTS`), then :class:`ToolTimeoutError` names the query."""
    for _ in range(SYNCTEX_ATTEMPTS):
        try:
            r = run(["synctex", *args], cwd=cwd, env=dict(os.environ), timeout=timeout)
        except ToolTimeoutError:
            continue
        return [line for line in text_lines(r.output) if _SYNCTEX_KEYS.match(line)]
    raise ToolTimeoutError(
        f"synctex {' '.join(args)} timed out {SYNCTEX_ATTEMPTS} times after {timeout} s"
    )


def _first(result: list[str], key: str) -> str:
    found = next((line.split(":", 1)[1] for line in result if line.startswith(f"{key}:")), None)
    if found is None:
        raise ToolError(f"synctex: no {key!r} in its output: {' | '.join(result)[:300]}")
    return found


#: a record with an input tag: type, tag, line (the rest of the line is compared as it is)
_RECORD = re.compile(r"^([\[(hgkx$vrf])(\d+),(\d+)")
#: a form reference: ``f<form number>:h,v``; the number counts the run's forms (a clipped
#: image, ...) and refers to no record, so it is not compared (like input tags)
_FORM = re.compile(r"^f\d+:")


def input_key(name: str, cwd: Path) -> tuple[str, bool]:
    """How a SyncTeX input is compared (§3.3 item 4): a ``.tex`` file below ``cwd`` by its path
    relative to ``cwd`` (``/./`` and separators normalised, case-insensitive on Windows), any
    other file by its name; and whether its line numbers are compared (only for ``.tex``
    files: generated files such as ``.toc`` or ``.bbl`` differ in their line numbers)."""
    given = Path(os.path.normpath(name.replace("\\", "/").replace("/./", "/")))
    path = str(given if given.is_absolute() else Path(os.path.normpath(cwd / given)))
    base = os.path.normpath(cwd)
    is_tex = path.lower().endswith(".tex")
    if is_tex and os.path.normcase(path).startswith(os.path.normcase(base) + os.sep):
        return path[len(base) + 1 :].replace("\\", "/"), True
    return Path(path).name, is_tex


@dataclass
class SyncTexRecords:
    """The records of a SyncTeX file in a form independent of tag numbers and paths
    (``"<page>|<type><file>,<line><rest>"``, ``*`` for the line of a generated file) and the
    lines with records per compared input (:func:`input_key`)."""

    records: list[str]
    lines: dict[str, set[int]]


def synctex_records(path: Path, cwd: Path) -> SyncTexRecords:
    """§3.3 item 4: the normalised records of a ``.synctex.gz`` file; ``!`` offsets,
    ``Input:`` lines, header and postamble are left out (:func:`chapmk.synctex.parse`), form
    numbers of form references too."""
    parsed = parse_synctex(path)
    keys = {tag: input_key(name, cwd) for tag, name in parsed.inputs.items()}
    out = SyncTexRecords([], {})
    for page in sorted(parsed.sheets):
        for line in parsed.sheets[page]:
            m = _RECORD.match(line)
            if m:
                key, numbered = keys.get(m.group(2), (f"?{m.group(2)}", True))
                if numbered:
                    out.lines.setdefault(key, set()).add(int(m.group(3)))
                number = m.group(3) if numbered else "*"
                line = f"{m.group(1)}{key},{number}{line[m.end() :]}"
            else:
                line = _FORM.sub("f:", line)
            out.records.append(f"{page}|{line}")
    return out


def _spread(lines: Sequence[int], count: int) -> list[int]:
    """``count`` of the sorted ``lines``, evenly spread (the middle one for 1)."""
    if not lines or count <= 0:
        return []
    if count >= len(lines):
        return list(lines)
    return [lines[(2 * i + 1) * len(lines) // (2 * count)] for i in range(count)]


def compare_synctex(
    ref_pdf: Path,
    got_pdf: Path,
    sources: Sequence[str],
    cwd: Path,
    *,
    samples: int = SYNCTEX_SAMPLES,
    report: Report | None = None,
) -> Report:
    """§3.3 item 4. All records of both SyncTeX files after normalisation
    (:func:`synctex_records`); then ``synctex view`` at ``samples`` lines per source file
    (evenly spread over its lines with records in the reference) and ``synctex edit`` at the
    resulting positions, which shows that editors find the records. ``sources`` are relative
    to ``cwd`` or absolute, in the form ``synctex view`` matches for the distribution
    (:meth:`TexDistribution.synctex_query`). No record found by ``synctex view`` for any
    source is a difference: the comparison would otherwise pass without querying (S11)."""
    report = report or Report()
    ref = synctex_records(ref_pdf.with_name(ref_pdf.stem + ".synctex.gz"), cwd)
    got = synctex_records(got_pdf.with_name(got_pdf.stem + ".synctex.gz"), cwd)
    report.compare("synctex records", ref.records, got.records)
    ref_views: list[list[str]] = []
    got_views: list[list[str]] = []
    ref_edits: list[list[str]] = []
    got_edits: list[list[str]] = []
    for source in sources:
        for line in _spread(sorted(ref.lines.get(input_key(source, cwd)[0], ())), samples):
            a = _synctex(["view", "-i", f"{line}:1:{source}", "-o", str(ref_pdf)], cwd)
            if not a:
                continue
            b = _synctex(["view", "-i", f"{line}:1:{source}", "-o", str(got_pdf)], cwd)
            ref_views.append([f"{source}:{line}", *a])
            got_views.append([f"{source}:{line}", *b])
            page, x, y = _first(a, "Page"), _first(a, "x"), _first(a, "y")
            ref_edits.append(_synctex(["edit", "-o", f"{page}:{x}:{y}:{ref_pdf}"], cwd))
            got_edits.append(_synctex(["edit", "-o", f"{page}:{x}:{y}:{got_pdf}"], cwd))
    report.compare("synctex view", ref_views, got_views)
    report.compare("synctex edit", ref_edits, got_edits)
    if sources and not ref_views:
        report.differences.append(
            Difference("synctex view", "no records found in the reference for any source file")
        )
    return report
