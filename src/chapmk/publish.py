"""Atomic replacement of the user-visible outputs (design §6.16 "Output replacement")."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path

RETRY_SECONDS = 2.0


def _tmp_name(target: Path) -> Path:
    return target.with_name(f".{target.name}.{os.getpid()}.chapmk-tmp")  # per process (C6)


def _replace(
    tmp: Path, target: Path, retry_seconds: float, replace: Callable[[Path, Path], None]
) -> Path:
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            replace(tmp, target)
            return target
        except PermissionError:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
    stem, _, suffixes = target.name.partition(".")
    fallback = target.with_name(f"{stem}.chapmk.{suffixes}" if suffixes else f"{stem}.chapmk")
    replace(tmp, fallback)
    return fallback


def publish(
    write: Callable[[Path], None],
    target: Path,
    *,
    retry_seconds: float = RETRY_SECONDS,
    replace: Callable[[Path, Path], None] = os.replace,
) -> Path:
    """Write via ``write(tmp)`` next to ``target`` and rename it atomically onto ``target``.

    A viewer may lock ``target`` on Windows: the rename is retried for ``retry_seconds``, then
    the file is published as ``<stem>.chapmk<suffixes>`` instead. Returns the path written.
    """
    return publish_all([(write, target)], retry_seconds=retry_seconds, replace=replace)[0]


def publish_all(
    items: Sequence[tuple[Callable[[Path], None], Path]],
    *,
    retry_seconds: float = RETRY_SECONDS,
    replace: Callable[[Path, Path], None] = os.replace,
) -> list[Path]:
    """Publish several files as one step (C16): all are written to temporary files first
    (the slow part, e.g. the PDF and SyncTeX merges), then renamed in the given order, one
    right after the other, so a viewer sees the old or the new set, apart from a
    microsecond window. A failed writer publishes nothing. Returns the paths written."""
    tmps: list[Path] = []
    try:
        for write, target in items:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = _tmp_name(target)
            tmps.append(tmp)
            write(tmp)
    except BaseException:
        for tmp in tmps:
            tmp.unlink(missing_ok=True)
        raise
    return [
        _replace(tmp, target, retry_seconds, replace)
        for tmp, (_, target) in zip(tmps, items, strict=True)
    ]


def copy_bytes(src: Path) -> Callable[[Path], None]:
    """Writer for :func:`publish` that copies ``src``."""

    def write(dst: Path) -> None:
        dst.write_bytes(src.read_bytes())

    return write


def text_writer(text: str) -> Callable[[Path], None]:
    """Writer for :func:`publish` that writes ``text`` (UTF-8)."""

    def write(dst: Path) -> None:
        dst.write_text(text, encoding="utf-8")

    return write
