"""Atomic replacement of the user-visible outputs (PLAN §6.16 "Output replacement")."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

RETRY_SECONDS = 2.0


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
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.chapmk-tmp")
    write(tmp)
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
