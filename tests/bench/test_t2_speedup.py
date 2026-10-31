"""Benchmark (manual, ``-m bench``): T2 on the thesis corpus sequentially (``-j 1``, the M4 tail
run) and with prediction (``-j 4``, M5). Run without xdist: the timings need idle cores."""

import shutil
import time
from pathlib import Path

import pytest

from fastinc.cli import main

pytestmark = [pytest.mark.bench, pytest.mark.slow]
PARA = "\n\n".join(["Additional text to make the chapter longer. " * 40] * 6)


def _t2(src: Path, jobs: str) -> float:
    ch3 = src / "chapters" / "ch3.tex"
    text = ch3.read_text()
    ch3.write_text(text.replace("\\section*{Remarks on ch3}", PARA + "\n\\section*{Remarks on ch3}"))
    start = time.monotonic()
    assert main(["build", "main.tex", "-j", jobs], cwd=src) == 0
    return time.monotonic() - start


def test_t2_speedup(thesis_template: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    live, cache = thesis_template
    times = {}
    for jobs in ("1", "4"):
        shutil.rmtree(live)
        shutil.copytree(cache, live, symlinks=True)
        times[jobs] = _t2(live, jobs)
    print(f"\nT2: -j 1 {times['1']:.1f} s, -j 4 {times['4']:.1f} s")
    assert times["4"] < times["1"]
