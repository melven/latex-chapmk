"""Prediction for parallel recompilation of successors (PLAN §6.9.3, M5).

Vectors map ``\\count`` register numbers to values; a missing register is 0 (the encoding of
the entry and checkpoint records).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

Vector = dict[int, int]


def normalized(v: Mapping[int, int]) -> Vector:
    """``v`` without zero entries (missing registers are 0)."""
    return {r: x for r, x in v.items() if x != 0}


@dataclass(frozen=True)
class SegmentVectors:
    """Entry and exit vector of a segment as compiled, and its absolute-assignment set."""

    entry: Vector
    exit: Vector
    absolute: frozenset[int]


PAGE = 0  # \\c@page is \\count0


def odd_start(page: int) -> int:
    """First page of a chapter that must start on a right-hand (odd) page."""
    return page if page % 2 else page + 1


def pass_through(seg: SegmentVectors) -> frozenset[int]:
    """Registers the segment does not modify: no absolute assignment, exit equal to entry
    (e.g. biblatex's ``maxextraname``, set at ``\\begin{document}`` from the ``.bbl``). They
    are not restored from checkpoints of excluded units, so a run carries their current
    values through (§6.9.3, M6)."""
    return frozenset(
        r
        for r in seg.entry.keys() | seg.exit.keys()
        if r not in seg.absolute and seg.entry.get(r, 0) == seg.exit.get(r, 0)
    )


def compose(seg: SegmentVectors, new_entry: Mapping[int, int], odd: bool = False) -> Vector:
    """Composition model: ``X'[r] = X[r]`` for ``r`` in the absolute set, otherwise
    ``X[r] + (E'[r] - E[r])``. With ``odd`` (the segment starts with a chapter in a
    twoside/openright document) the page counter moves with the odd start page instead:
    a blank page is inserted or dropped before the chapter."""
    out: Vector = {}
    for r in seg.exit.keys() | seg.entry.keys() | new_entry.keys():
        x = seg.exit.get(r, 0)
        if r in seg.absolute:
            pass
        elif r == PAGE and odd:
            x += odd_start(new_entry.get(r, 0)) - odd_start(seg.entry.get(r, 0))
        else:
            x += new_entry.get(r, 0) - seg.entry.get(r, 0)
        out[r] = x
    return normalized(out)


def predict(
    order: Sequence[str],
    vectors: Mapping[str, SegmentVectors],
    start: str,
    entry: Mapping[int, int],
    odd: frozenset[str] = frozenset(),
) -> dict[str, tuple[Vector, Vector]]:
    """Predicted (entry, exit) of ``start`` (with the given new entry) and every later
    segment of ``order``; the exit of one segment is the entry of the next. ``odd``: the
    segments that start on an odd page (see :func:`compose`)."""
    out: dict[str, tuple[Vector, Vector]] = {}
    current = normalized(entry)
    for seg in order[order.index(start) :]:
        x = compose(vectors[seg], current, seg in odd)
        out[seg] = (current, x)
        current = x
    return out


def partition(weights: Sequence[float], parts: int) -> list[list[int]]:
    """Split item indices ``0..n-1`` into at most ``parts`` contiguous groups of similar
    total weight (greedy: a group closes when it reaches the remaining average)."""
    n = len(weights)
    parts = max(1, min(parts, n))
    groups: list[list[int]] = []
    i = 0
    while i < n:
        left = parts - len(groups)
        target = sum(weights[i:]) / left
        group = [i]
        acc = weights[i]
        i += 1
        # keep at least one item for each remaining group
        while i < n and n - i > left - 1 and acc + weights[i] / 2 <= target:
            acc += weights[i]
            group.append(i)
            i += 1
        groups.append(group)
    return groups


_SETCOUNTER = re.compile(r"\\setcounter\s*\{([^{}]+)\}\s*\{(-?\d+)\}")
_CKPT = re.compile(r"^(\\fastinc@ckpt\{[^{}]*\}\{)([^{}]*)(\}\s*)$")


def rewrite_checkpoint(
    stmts: Sequence[str],
    exit: Mapping[int, int],
    registers: Mapping[str, int],
    drop: frozenset[int] = frozenset(),
) -> list[str]:
    """Unit-aux statements with the checkpoint (``\\\\@setckpt`` counters and the complete
    ``\\\\fastinc@ckpt`` vector) set to the predicted ``exit``; ``registers`` maps counter
    names to register numbers."""
    out = []
    for stmt in stmts:
        if stmt.startswith("\\@setckpt{"):

            def counter(m: re.Match[str]) -> str:
                reg = registers.get(m.group(1))
                if reg is not None and reg in drop:
                    return ""
                value = exit.get(reg, 0) if reg is not None and reg >= 0 else int(m.group(2))
                return f"\\setcounter{{{m.group(1)}}}{{{value}}}"

            stmt = _SETCOUNTER.sub(counter, stmt)
            # no empty lines: they would be \par inside the (non-long) \@setckpt argument
            stmt = "\n".join(line for line in stmt.split("\n") if line.strip())
        else:
            m = _CKPT.match(stmt)
            if m:
                regs = sorted({int(x.split("=")[0]) for x in m.group(2).split(",") if "=" in x})
                regs = sorted((set(regs) | set(exit)) - drop)
                vec = "".join(f"{r}={exit.get(r, 0)}," for r in regs)
                stmt = f"{m.group(1)}{vec}{m.group(3)}"
        out.append(stmt)
    return out
