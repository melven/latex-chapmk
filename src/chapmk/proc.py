"""Running external programs: argument lists only (no shell), combined output captured.

Every program runs in its own process group (session) and is registered while it runs, so
an interrupted build kills all of them (:func:`terminate_all`, C8): orphaned pdflatex
processes would otherwise keep writing into run directories that the next build reuses.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from chapmk.errors import ToolError, ToolTimeoutError


@dataclass(frozen=True)
class ProcResult:
    """Outcome of :func:`run`: arguments, exit code, combined stdout/stderr, wall time."""

    argv: tuple[str, ...]
    returncode: int
    output: str
    seconds: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0


_LOCK = threading.Lock()
_RUNNING: set[subprocess.Popen[bytes]] = set()
_STOPPING = threading.Event()
#: seconds between SIGTERM and SIGKILL of a process group
GRACE_SECONDS = 1.0


class Interrupted(BaseException):
    """The build is being stopped (signal); raised by :func:`run` for new programs."""


def _group_kwargs() -> dict[str, object]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill(p: subprocess.Popen[bytes]) -> None:
    """Stop ``p`` and its process group (POSIX: SIGTERM, then SIGKILL after a grace time)."""
    if p.poll() is not None:
        return
    if sys.platform == "win32":
        p.kill()
        return
    try:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            p.wait(GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def terminate_all() -> None:
    """Kill every running program and refuse new ones until :func:`allow_runs`."""
    _STOPPING.set()
    with _LOCK:
        running = list(_RUNNING)
    for p in running:
        _kill(p)


def allow_runs() -> None:
    """Allow programs again (after :func:`terminate_all`, once all threads are done)."""
    _STOPPING.clear()


def run(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float | None = None,
    log_path: Path | None = None,
) -> ProcResult:
    """Run ``argv`` in ``cwd`` with exactly the environment ``env``.

    stdin is closed, so programs that prompt cannot hang. The combined output is returned and,
    if ``log_path`` is given, also written there. A missing program or a timeout raises
    :class:`ToolError` (a timeout: :class:`ToolTimeoutError`); a non-zero exit code does not.
    """
    if _STOPPING.is_set():
        raise Interrupted
    start = time.monotonic()
    try:
        p = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **_group_kwargs(),  # type: ignore[call-overload]
        )
    except FileNotFoundError as err:
        raise ToolError(f"program not found: {argv[0]}") from err
    with _LOCK:
        _RUNNING.add(p)
    try:
        if _STOPPING.is_set():  # terminate_all ran between the check and the registration
            _kill(p)
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as err:
        _kill(p)
        p.communicate()
        raise ToolTimeoutError(f"{argv[0]} timed out after {timeout} s") from err
    except BaseException:  # KeyboardInterrupt in the main thread
        _kill(p)
        raise
    finally:
        with _LOCK:
            _RUNNING.discard(p)
    if _STOPPING.is_set():
        raise Interrupted
    output = out.decode("utf-8", "replace")
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output, encoding="utf-8")
    return ProcResult(tuple(argv), p.returncode, output, time.monotonic() - start)
