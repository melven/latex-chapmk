"""File helpers (D1): digests and atomic writes.

Every file the driver keeps between builds (canonical state, picture cache, stamps, caches)
is written with :func:`write_atomic`: a temporary file next to the target, then
``os.replace``. A kill or a full disk during the write leaves the old file or none, never a
truncated one that later runs would read (C7). Text is encoded as UTF-8 with
``surrogateescape`` (bytes of the sources survive a round trip).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path


def digest(path: Path) -> str:
    """sha256 of the file's bytes (hex)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def changed_files(base: Path, digests: Mapping[str, str]) -> list[str]:
    """Names (relative to ``base``) of ``digests`` whose file is missing or has another
    digest, in the order of ``digests``."""
    return [
        name
        for name, stored in digests.items()
        if not (base / name).is_file() or digest(base / name) != stored
    ]


def read_log(path: Path) -> str:
    """A log or another text file for messages and searches, decoded as UTF-8 with
    replacement characters (not in the locale's encoding, e.g. cp1252 on Windows)."""
    return path.read_bytes().decode("utf-8", "replace")


def read_raw(path: Path) -> str:
    """A text file TeX or a tool wrote, decoded as UTF-8 with ``surrogateescape``: every byte
    survives a round trip through :func:`write_atomic`."""
    return path.read_bytes().decode("utf-8", "surrogateescape")


def _bytes(data: bytes | str) -> bytes:
    return data if isinstance(data, bytes) else data.encode("utf-8", "surrogateescape")


def write_atomic(path: Path, data: bytes | str) -> None:
    """Replace ``path`` by ``data`` atomically (parents are created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(_bytes(data))
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_if_changed(path: Path, data: bytes | str) -> bool:
    """:func:`write_atomic` unless the file already has this content (keeps the mtime and
    TeX's change detection quiet). Returns whether the file was written."""
    raw = _bytes(data)
    if path.is_file() and path.read_bytes() == raw:
        return False
    write_atomic(path, raw)
    return True


def copy_atomic(src: Path, dst: Path) -> None:
    """Copy the bytes of ``src`` to ``dst`` atomically."""
    write_atomic(dst, src.read_bytes())
