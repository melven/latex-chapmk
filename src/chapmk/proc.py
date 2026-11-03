"""Running external programs: argument lists only (no shell), combined output captured."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from chapmk.errors import ToolError


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
    :class:`ToolError`; a non-zero exit code does not.
    """
    start = time.monotonic()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as err:
        raise ToolError(f"program not found: {argv[0]}") from err
    except subprocess.TimeoutExpired as err:
        raise ToolError(f"{argv[0]} timed out after {timeout} s") from err
    output = completed.stdout.decode("utf-8", "replace")
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output, encoding="utf-8")
    return ProcResult(tuple(argv), completed.returncode, output, time.monotonic() - start)
