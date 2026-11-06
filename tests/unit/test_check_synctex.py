"""check.py without TeX: the SyncTeX part of the §3.3 comparison (normalised records, calls)."""

from __future__ import annotations

import gzip
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


def _synctex(path: Path, inputs: dict[str, str], body: str, offsets: int) -> Path:
    """A ``.synctex.gz`` file with ``inputs`` (tag -> name) and one page ``body``."""
    head = "SyncTeX Version:1\n" + "".join(f"Input:{t}:{n}\n" for t, n in inputs.items())
    text = (
        f"{head}Output:pdf\nMagnification:1000\nUnit:1\nX Offset:0\nY Offset:0\nContent:\n"
        f"!{offsets}\n{{1\n{body}}}1\n!{offsets + 7}\nPostamble:\nCount:3\n!{offsets}\n"
        "Post scriptum:\n"
    )
    path.write_bytes(gzip.compress(text.encode()))
    return path


def test_synctex_records_are_independent_of_tags_paths_and_offsets(tmp_path: Path) -> None:
    """§3.3 item 4: tags renumbered, the main file in TeX Live's and MiKTeX's path form, a
    generated .toc in another directory with other line numbers, other ! offsets: equal; a
    changed position or source line: a difference."""
    src = tmp_path / "s"
    ref = _synctex(
        tmp_path / "ref.synctex.gz",
        {"1": f"{src}/./main.tex", "2": f"{tmp_path}/b/full/main.toc"},
        "[1,3:47,48:26,44,0\n(2,36:0,0:0,0,0\nh1,5:10,20:30,40,50\n]\n",
        120,
    )
    body = "[2,3:47,48:26,44,0\n(1,53:0,0:0,0,0\nh2,5:10,20:30,40,50\n]\n"
    got = _synctex(
        tmp_path / "got.synctex.gz",
        {"1": f"{src}/.chapmk/main/runs/r3/main.toc", "2": f"{src}/main.tex"},
        body,
        97,
    )
    a, b = check.synctex_records(ref, src), check.synctex_records(got, src)
    assert a.records == b.records and len(a.records) == 4
    assert a.records[1] == "1|(main.toc,*:0,0:0,0,0"
    assert a.lines == b.lines == {"main.tex": {3, 5}}
    moved = _synctex(
        tmp_path / "m.synctex.gz", {"2": f"{src}/main.tex"}, body.replace("10,20", "10,21"), 5
    )
    assert check.synctex_records(moved, src).records != a.records


def test_input_key(tmp_path: Path) -> None:
    assert check.input_key("chapters/ch1.tex", tmp_path) == ("chapters/ch1.tex", True)
    assert check.input_key(f"{tmp_path}/./chapters/ch1.tex", tmp_path) == ("chapters/ch1.tex", True)
    assert check.input_key(f"{tmp_path}/main.toc", tmp_path) == ("main.toc", False)
    assert check.input_key("/usr/share/texmf/tex/x.tex", tmp_path) == ("x.tex", True)


def test_spread() -> None:
    assert check._spread([], 1) == []
    assert check._spread([3, 5, 9], 1) == [5]
    assert check._spread([1, 2, 3, 4, 5, 6], 2) == [2, 5]
    assert check._spread([1, 2], 5) == [1, 2]
