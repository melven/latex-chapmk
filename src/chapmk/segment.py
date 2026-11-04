"""Segment ids (design §6.4): the document is ``G0, U1, G1, ..., Un, Gn``. Unit segment
``U<k>`` is the k-th ``\\include`` (1-based); glue segment ``G<k>`` is the main-file text after
it (``G0``: before the first include, with the preamble's output)."""

from __future__ import annotations


def unit_id(k: int) -> str:
    """Segment id of the k-th include."""
    return f"U{k}"


def glue_id(k: int) -> str:
    """Segment id of the glue after the k-th include (0: before the first)."""
    return f"G{k}"


def seg_index(seg: str) -> int:
    """``k`` of ``U<k>`` or ``G<k>``."""
    return int(seg[1:])


def is_unit(seg: str | None) -> bool:
    return seg is not None and seg.startswith("U")


def is_glue(seg: str | None) -> bool:
    return seg is not None and seg.startswith("G")


def is_segment(name: str) -> bool:
    """Whether ``name`` is a segment id (record point names also include ``load``, ...)."""
    return name[:1] in ("U", "G") and name[1:].isdigit()


def unit_ids(n: int) -> list[str]:
    """``U1 ... Un``."""
    return [unit_id(k) for k in range(1, n + 1)]


def glue_ids(n: int) -> list[str]:
    """``G0 ... Gn``."""
    return [glue_id(k) for k in range(n + 1)]


def document_order(n: int) -> list[str]:
    """All segment ids of a document with ``n`` includes, in document order."""
    return [glue_id(0)] + [s for k in range(1, n + 1) for s in (unit_id(k), glue_id(k))]


def position(seg: str) -> int:
    """Sort key in document order (``G0`` = 0, ``U1`` = 1, ``G1`` = 2, ...)."""
    k = seg_index(seg)
    return 2 * k - 1 if is_unit(seg) else 2 * k
