"""Parallel scenarios (design §8.2, §6.9.3): parallel recompilation of successors with prediction.

Builds use ``-j 4``; each asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path
from typing import Any

import pytest
from _helpers import build, edit, selections

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]

ALL = [f"chapters/ch{k}" for k in range(1, 7)] + ["chapters/appA", "chapters/appB"]
PARA = "\n\n".join(["Additional text to make the chapter longer. " * 40] * 6)


def checked(thesis: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    rc, rep = build(thesis, "--check", "-j", "4")
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "PASS" in out.out, out.out
    return rep


def batches(rep: dict[str, Any]) -> list[list[list[str] | None]]:
    out: dict[int, list[list[str] | None]] = {}
    for r in rep["runs"]:
        out.setdefault(r["batch"], []).append(r["selection"])
    return [out[k] for k in sorted(out)]


def mispredictions(rep: dict[str, Any]) -> list[str]:
    return [
        reason
        for r in rep["runs"]
        for reasons in r["reasons"].values()
        for reason in reasons
        if reason.startswith("misprediction")
    ]


def ch(thesis: Path, name: str) -> Path:
    return thesis / "chapters" / f"{name}.tex"


def test_t2_parallel_successors(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T2 with prediction: ch3 gets longer -> ch3, then ch4..appB in parallel runs."""
    edit(ch(thesis, "ch3"), "\\section*{Remarks on ch3}", PARA + "\n\\section*{Remarks on ch3}")
    rep = checked(thesis, capsys)
    b = batches(rep)
    assert b[0] == [["chapters/ch3"]]
    assert len(b[1]) > 1, b  # successors in several parallel runs
    assert set(ALL[3:]) <= {a for sel in b[1] for a in sel or ALL}
    assert mispredictions(rep) == []


def test_t10_page_parity_parallel(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T10: ch1 gets longer (twoside, openright: later chapters move by the blank pages
    before them) -> predicted by the odd-start model, no misprediction."""
    edit(ch(thesis, "ch1"), "\\section*{Remarks on ch1}", PARA + "\n\\section*{Remarks on ch1}")
    rep = checked(thesis, capsys)
    assert selections(rep)[0] == ["chapters/ch1"]
    assert any(len(b) > 1 for b in batches(rep))
    assert mispredictions(rep) == []
    assert set(rep["compiled"]) == set(ALL)


def test_misprediction_path(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """ch1 gets longer and ch5 has a typo: both are compiled in one parallel batch with
    ch1's old exit predicted for ch5's run -> misprediction; ch5 and the units after ch1's
    run are compiled again; output correct."""
    edit(ch(thesis, "ch1"), "\\section*{Remarks on ch1}", PARA + "\n\\section*{Remarks on ch1}")
    edit(ch(thesis, "ch5"), "Further reading:", "Furhter reading:")
    rep = checked(thesis, capsys)
    assert batches(rep)[0] == [["chapters/ch1"], ["chapters/ch5"]]
    assert any("exit of chapters/ch1" in m for m in mispredictions(rep)), rep["runs"]
    assert set(rep["compiled"]) == set(ALL)


def test_local_open_any(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """ch3 is included in a group with KOMA's open=any (as the reference document's notation
    chapter): it does not start on an odd page. ch2 grows by exactly one page; ch3 moves by one
    page, predicted from ch3's own recorded openright flag, not the document's."""
    edit(
        thesis / "main.tex",
        "\\include{chapters/ch3}",
        "\\begingroup\\KOMAoptions{open=any}\\include{chapters/ch3}\\endgroup",
    )
    assert checked(thesis, capsys)["mode"] == "cold"
    with ch(thesis, "ch2").open("a") as f:
        f.write("\n\\newpage\\mbox{}\\newpage\n")
    rep = checked(thesis, capsys)
    assert selections(rep)[0] == ["chapters/ch2"]
    assert mispredictions(rep) == [], rep["runs"]
