"""Exclusive lock of a build directory (C6): one chapmk process per build directory.

An editor build on save and a terminal build would otherwise take the same run names,
remove each other's run directories and interleave canon commits. The lock is an OS file
lock on ``<build>/lock`` (``fcntl.flock`` / ``msvcrt.locking``): it is released when the
process ends, also when it is killed, so there are no stale locks.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from chapmk.errors import ChapmkError

LOCK_FILE = "lock"
POLL_SECONDS = 0.2
#: Windows locks are mandatory (a locked byte cannot be read by others): the lock covers one
#: byte far beyond the holder's PID at the start of the file
_WIN_LOCK_OFFSET = 1 << 30


class LockedError(ChapmkError):
    """The build directory is locked by another process (``--no-wait``)."""


def _try_lock(f: IO[bytes]) -> bool:
    if sys.platform == "win32":
        import msvcrt

        f.seek(_WIN_LOCK_OFFSET)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(f: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        f.seek(_WIN_LOCK_OFFSET)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _holder(path: Path) -> str:
    try:
        pid = path.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return ""
    return f" (pid {pid})" if pid.isdigit() else ""


@contextmanager
def build_lock(
    build_dir: Path, *, wait: bool = True, say: Callable[[str], None] = lambda _m: None
) -> Iterator[None]:
    """Hold the exclusive lock of ``build_dir`` while the block runs. If another process
    holds it: wait (with one message via ``say``), or raise :class:`LockedError`."""
    build_dir.mkdir(parents=True, exist_ok=True)
    path = build_dir / LOCK_FILE
    with path.open("a+b") as f:
        if not _try_lock(f):
            holder = _holder(path)
            if not wait:
                raise LockedError(f"{build_dir} is in use by another chapmk process{holder}")
            say(f"waiting for another chapmk process{holder} using {build_dir}")
            while not _try_lock(f):
                time.sleep(POLL_SECONDS)
        try:
            f.seek(0)
            f.truncate()
            f.write(str(os.getpid()).encode("ascii"))
            f.flush()
            yield
        finally:
            _unlock(f)
