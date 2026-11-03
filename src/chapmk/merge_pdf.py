"""PDF merge (PLAN §6.11, S9): pages of several runs into one PDF with links, outline, labels."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pikepdf
from pikepdf import Array, Dictionary, Name, String

from chapmk.errors import FallbackError, SelfCheckError

_DUMMY = re.compile(r"name\{([^}]*)\} has been referenced but does not exist")


class MergeError(FallbackError):
    """The merge cannot reproduce the document (missing destination, ...); fall back."""


@dataclass(frozen=True)
class PageSource:
    """A page to take: the run's PDF, 0-based page index, ``\\c@page`` and ``\\thepage``.
    ``check_label``: the run's own page labels index its pages (no extra picture pages
    before this one, which hyperref does not count), so they can verify the merged label."""

    pdf: Path
    index: int
    value: int
    label: str
    check_label: bool = True


@dataclass(frozen=True)
class OutlineEntry:
    """An outline item in document order (S6): level, open state, named destination, title."""

    level: int
    open: bool
    dest: str
    title: bytes


@dataclass(frozen=True)
class MergeStats:
    pages: int
    destinations: int
    outline_items: int


def dummy_destinations(log: Path) -> set[str]:
    """Names pdfTeX replaced by dummy destinations (referenced but not defined in the run)."""
    if not log.is_file():
        return set()
    return set(_DUMMY.findall(log.read_text(errors="replace")))


def _roman(n: int) -> str:
    out = ""
    for value, sym in (
        (1000, "m"),
        (900, "cm"),
        (500, "d"),
        (400, "cd"),
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ):
        while n >= value:
            out += sym
            n -= value
    return out


def _alph(n: int) -> str:
    return chr(ord("a") + n - 1) if 1 <= n <= 26 else ""


def label_style(value: int, label: str) -> str | None:
    """PDF page-label style producing ``label`` for ``value`` (``/D``, ``/r``, ...), if any."""
    for style, text in (
        ("/D", str(value)),
        ("/r", _roman(value)),
        ("/R", _roman(value).upper()),
        ("/a", _alph(value)),
        ("/A", _alph(value).upper()),
    ):
        if text and text == label:
            return style
    return None


def page_labels(labels: Sequence[tuple[int, str]]) -> Array:
    """``/Nums`` array of a page-label number tree for (``\\c@page``, ``\\thepage``) per page."""
    nums: list[Any] = []
    prev: tuple[str, int] | None = None
    for i, (value, label) in enumerate(labels):
        style = label_style(value, label)
        if style is None:
            nums += [i, Dictionary(P=String(label))]
            prev = None
        elif prev is None or prev[0] != style or value != prev[1] + 1:
            nums += [i, Dictionary(S=Name(style), St=value)]
            prev = (style, value)
        else:
            prev = (style, value)
    return Array(nums)


class _Sources:
    """Open run PDFs with page-object → index maps."""

    def __init__(self) -> None:
        self.pdfs: dict[Path, pikepdf.Pdf] = {}
        self.index: dict[Path, dict[Any, int]] = {}  # page objgen -> index

    def get(self, path: Path) -> pikepdf.Pdf:
        if path not in self.pdfs:
            pdf = pikepdf.open(path)
            self.pdfs[path] = pdf
            self.index[path] = {p.objgen: i for i, p in enumerate(pdf.pages)}
        return self.pdfs[path]

    def close(self) -> None:
        for pdf in self.pdfs.values():
            pdf.close()


def _dest_array(value: Any) -> Any:
    return value.D if isinstance(value, Dictionary) else value


def _referenced_names(pdf: pikepdf.Pdf) -> set[str]:
    names: set[str] = set()
    for page in pdf.pages:
        for annot in page.get("/Annots", []):
            action = annot.get("/A")
            if action is not None and action.get("/S") == "/GoTo" and isinstance(action.D, String):
                names.add(str(action.D))
            elif isinstance(annot.get("/Dest"), String):
                names.add(str(annot.Dest))
    return names


def merge_pdf(
    pages: Sequence[PageSource],
    outline: Sequence[OutlineEntry],
    catalog_from: Path,
    out: Path,
) -> MergeStats:
    """Write the merged PDF to ``out`` (§6.11 steps 1-6).

    Named destinations are taken from the run whose pages define them, without the run's
    dummies; for duplicates the first in merged page order wins (S6). A referenced name that no
    run defines gets pdfTeX's dummy destination (first page, ``/Fit``), as in a plain build; a
    name defined only on pages that were not taken raises :class:`MergeError`.
    """
    sources = _Sources()
    merged = pikepdf.new()
    try:
        where: dict[tuple[Path, int], int] = {}
        for src in pages:
            pdf = sources.get(src.pdf)
            where[(src.pdf, src.index)] = len(merged.pages)
            merged.pages.append(pdf.pages[src.index])

        chosen: dict[str, tuple[int, Any]] = {}
        defined: set[str] = set()  # names some run defines (not as dummy), on any page
        for path, pdf in sources.pdfs.items():
            dummies = dummy_destinations(path.with_suffix(".log"))
            names = pdf.Root.get("/Names")
            if names is None or "/Dests" not in names:
                continue
            for raw_name, value in pikepdf.NameTree(names.Dests).items():
                name = raw_name.decode("latin-1") if isinstance(raw_name, bytes) else raw_name
                if name in dummies:
                    continue
                defined.add(name)
                arr = _dest_array(value)
                target = where.get((path, sources.index[path].get(arr[0].objgen, -1)))
                if target is not None and (name not in chosen or target < chosen[name][0]):
                    chosen[name] = (target, arr)
        tree = pikepdf.NameTree.new(merged)
        for name in sorted(chosen):
            target, arr = chosen[name]
            rest = [
                merged.copy_foreign(x) if isinstance(x, pikepdf.Object) and x.is_indirect else x
                for x in list(arr)[1:]
            ]
            tree[name] = Dictionary(D=Array([merged.pages[target].obj, *rest]))
        merged.Root.Names = Dictionary(Dests=tree.obj)

        missing = (_referenced_names(merged) | {e.dest for e in outline}) - chosen.keys()
        lost = missing & defined
        if lost:  # defined by a run, but on a page that was not taken: a selection error
            raise MergeError(f"unresolved destinations: {', '.join(sorted(lost)[:5])}")
        for name in missing:  # undefined everywhere: pdfTeX's dummy destination (S6)
            tree[name] = Dictionary(D=Array([merged.pages[0].obj, Name.Fit]))

        _normalize_font_descriptors(merged)
        _write_outline(merged, outline)
        merged.Root.PageLabels = Dictionary(Nums=page_labels([(p.value, p.label) for p in pages]))
        _check_page_labels(merged, pages, sources)
        cat = sources.get(catalog_from)
        for key in ("/PageMode", "/PageLayout", "/ViewerPreferences"):
            if key in cat.Root:
                value = cat.Root[key]
                if isinstance(value, (Dictionary, Array)):  # copy containers via indirect objects
                    value = value if value.is_indirect else cat.make_indirect(value)
                    value = merged.copy_foreign(value)
                merged.Root[key] = value
        merged.docinfo = merged.copy_foreign(cat.docinfo)  # type: ignore[assignment]
        tmp = out.with_name(f".{out.name}.merge-tmp")
        merged.save(tmp, deterministic_id=True)
        tmp.replace(out)
        return MergeStats(len(merged.pages), len(chosen), len(outline))
    finally:
        merged.close()
        sources.close()


def _check_page_labels(merged: pikepdf.Pdf, pages: Sequence[PageSource], sources: _Sources) -> None:
    """Self-check (C14): each merged page shows the label hyperref gave it in its run (runs
    without ``/PageLabels`` are not checked)."""
    for i, src in enumerate(pages):
        pdf = sources.get(src.pdf)
        if not src.check_label or "/PageLabels" not in pdf.Root:
            continue
        expected = pikepdf.Page(pdf.pages[src.index]).label
        got = pikepdf.Page(merged.pages[i]).label
        if got != expected:
            raise SelfCheckError(
                f"page {i + 1}: merged page label {got!r}, the run wrote {expected!r} "
                f"({src.pdf.parent.name})"
            )


def _font_name(desc: Any) -> str:
    """FontName without the subset tag (``ABCDEF+``)."""
    name = str(desc.get("/FontName", ""))[1:]
    return name[7:] if len(name) > 7 and name[6] == "+" else name


def _normalize_font_descriptors(pdf: pikepdf.Pdf) -> None:
    """Font descriptor metrics as one pdfTeX run of the whole document writes them (M7).

    pdfTeX writes one descriptor per font. For a font that also occurs in an included PDF
    (an embedded figure, ``/PTEX.FileName``), its metrics come from the font file: Ascent and
    CapHeight = FontBBox top, Descent = FontBBox bottom, no XHeight; otherwise from the TFM.
    Runs see only some of the figures, so their copies differ; text extraction (§3.3 item 2)
    uses these metrics.
    """
    descriptors: dict[str, list[Any]] = {}
    in_figures: set[str] = set()
    seen: set[tuple[int, int]] = set()

    def walk(resources: Any, figure: bool) -> None:
        if not isinstance(resources, Dictionary):
            return
        for font in resources.get("/Font", Dictionary()).values():
            desc = font.get("/FontDescriptor")
            if desc is None or desc.objgen in seen:
                if desc is not None and figure:
                    in_figures.add(_font_name(desc))
                continue
            seen.add(desc.objgen)
            descriptors.setdefault(_font_name(desc), []).append(desc)
            if figure:
                in_figures.add(_font_name(desc))
        for xobj in resources.get("/XObject", Dictionary()).values():
            if xobj.get("/Subtype") != Name.Form or xobj.objgen in seen:
                continue
            seen.add(xobj.objgen)
            walk(xobj.get("/Resources"), figure or "/PTEX.FileName" in xobj)

    for page in pdf.pages:
        walk(page.obj.get("/Resources"), False)
    for name, descs in descriptors.items():
        if name in in_figures:
            for d in descs:
                bbox = d.get("/FontBBox")
                if bbox is None:
                    continue
                d.Ascent = bbox[3]
                d.CapHeight = bbox[3]
                d.Descent = bbox[1]
                if "/XHeight" in d:
                    del d["/XHeight"]
        else:
            tfm = next((d for d in descs if "/XHeight" in d), None)
            if tfm is None:
                continue
            for d in descs:
                for key in ("/Ascent", "/CapHeight", "/Descent", "/XHeight"):
                    d[key] = tfm[key]


def _write_outline(pdf: pikepdf.Pdf, entries: Sequence[OutlineEntry]) -> None:
    """Outline tree with bookmark's rule: parent = nearest previous entry of lower level."""
    if not entries:
        return
    root = pdf.make_indirect(Dictionary(Type=Name.Outlines))
    stack: list[tuple[int, Any]] = [(-(10**6), root)]
    opened: dict[tuple[int, int], bool] = {}
    for e in entries:
        while stack[-1][0] >= e.level:
            stack.pop()
        parent = stack[-1][1]
        item = pdf.make_indirect(
            Dictionary(
                Title=String(e.title), Parent=parent, A=Dictionary(S=Name.GoTo, D=String(e.dest))
            )
        )
        opened[item.objgen] = e.open
        if "/Last" in parent:
            parent.Last.Next = item
            item.Prev = parent.Last
        else:
            parent.First = item
        parent.Last = item
        stack.append((e.level, item))

    def visible(node: Any) -> int:
        total, child = 0, node.get("/First")
        while child is not None:
            below = visible(child)
            is_open = opened[child.objgen]
            if "/First" in child:
                child.Count = below if is_open else -below
            total += 1 + (below if is_open else 0)
            child = child.get("/Next")
        return total

    root.Count = visible(root)
    pdf.Root.Outlines = root
