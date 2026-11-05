"""check.py without TeX: the synctex calls of the §3.3 comparison."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from chapmk import check
from chapmk.errors import ToolTimeoutError
from chapmk.proc import ProcResult


def _stub(hangs: int, calls: list[Sequence[str]]) -> Any:
    """``run`` replacement: the first ``hangs`` calls time out, later ones answer."""

    def run(argv: Sequence[str], **kwargs: Any) -> ProcResult:
        calls.append(argv)
        assert kwargs["timeout"] == check.SYNCTEX_TIMEOUT
        if len(calls) <= hangs:
            raise ToolTimeoutError(f"{argv[0]} timed out after {kwargs['timeout']} s")
        return ProcResult(tuple(argv), 0, "SyncTeX result begin\nPage:3\nx:1.5\nOther:9\n", 0.0)

    return run


def test_synctex_hang_is_repeated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MiKTeX's synctex on Windows rarely hangs at start-up: the call is killed and repeated."""
    calls: list[Sequence[str]] = []
    monkeypatch.setattr(check, "run", _stub(1, calls))
    assert check._synctex(["view", "-i", "1:1:a.tex", "-o", "a.pdf"], tmp_path) == [
        "Page:3",
        "x:1.5",
    ]
    assert len(calls) == 2 and calls[0] == calls[1]


def test_synctex_hanging_every_time_names_the_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Sequence[str]] = []
    monkeypatch.setattr(check, "run", _stub(check.SYNCTEX_ATTEMPTS, calls))
    with pytest.raises(ToolTimeoutError, match=r"synctex edit -o 1:2:3:a\.pdf timed out 2 times"):
        check._synctex(["edit", "-o", "1:2:3:a.pdf"], tmp_path)
    assert len(calls) == check.SYNCTEX_ATTEMPTS
