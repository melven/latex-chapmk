"""M7 scenarios (PLAN §6.17): picture cache behind the user's TikZ externalize.

The ``pictures`` corpus calls ``\\tikzexternalize`` (with the reference document's todo-note
wrapper). Each build asserts §3.3 against ``--full`` (``--check``); ``--full`` itself is
compared with latexmk and real externalize in ``tests/acceptance/test_full_vs_latexmk.py``.
"""

import re
from pathlib import Path
from typing import Any

import pytest
from _helpers import build, edit, selections

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]

PLOTS = "chapters/plots"
_RECORD = re.compile(r"^chapmk-picture: ([xu]) \S+ .*?(\S+)$", re.MULTILINE)


def checked(src: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    rc, rep = build(src, "--check")
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "PASS" in out.out, out.out
    return rep


def reasons(rep: dict[str, Any]) -> list[str]:
    return [x for r in rep["runs"] for rs in r["reasons"].values() for x in rs]


def records(src: Path, run: str) -> list[tuple[str, str]]:
    """(kind, segment) of the picture records of a run."""
    log = (src / ".chapmk" / "runs" / run / "main.log").read_text(errors="replace")
    return _RECORD.findall(log)


@pytest.fixture
def pictures(copy_corpus, capsys: pytest.CaptureFixture[str]) -> Path:  # type: ignore[no-untyped-def]
    src: Path = copy_corpus("pictures")
    rep = checked(src, capsys)
    assert rep["mode"] == "cold"
    assert any(r.startswith("pictures exported") for r in reasons(rep))
    figs = list((src / ".chapmk" / "fig").glob("*.pdf"))
    assert len(figs) >= 7  # unit and glue pictures; todo notes stay inline
    return src


def test_typo_reuses_pictures(pictures: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A typo in a picture-heavy unit: one run of that unit, every picture embedded from the
    cache (no export, no further pass)."""
    edit(pictures / "chapters" / "plots.tex", "Some text before", "Some txet before")
    rep = checked(pictures, capsys)
    assert selections(rep) == [[PLOTS]]
    assert not any(r.startswith("pictures exported") for r in reasons(rep))
    recs = records(pictures, rep["runs"][0]["name"])
    assert ("u", "U1") in recs and ("x", "U1") not in recs


def test_changed_picture_is_exported_and_embedded(
    pictures: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A changed picture is typeset inline and exported, then the unit is compiled again with
    the figure embedded (result equal to externalize)."""
    edit(pictures / "chapters" / "plots.tex", "samples=400", "samples=401")
    rep = checked(pictures, capsys)
    assert {tuple(s or ()) for s in selections(rep)} == {(PLOTS,)}
    assert "pictures exported (1)" in reasons(rep)
    last = records(pictures, rep["runs"][-1]["name"])
    assert ("x", "U1") not in last


def test_picture_showing_a_reference(pictures: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A picture in chapters/diagrams shows \\ref{fig:axis}. A figure inserted before that
    figure changes the label value: the picture's key changes and it is exported again (an
    embedded figure would show the old number)."""
    edit(
        pictures / "chapters" / "plots.tex",
        "\\todo{A todo note",
        "\\begin{figure}[htbp]\\centering X\\caption{Inserted}\\end{figure}\n\\todo{A todo note",
    )
    rep = checked(pictures, capsys)
    exported_in = {
        unit
        for r in rep["runs"]
        for unit, rs in r["reasons"].items()
        if any(x.startswith("pictures exported") for x in rs)
    }
    assert "chapters/diagrams" in exported_in


def test_page_shift_keeps_pictures(pictures: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """chapters/plots grows by pages: chapters/diagrams is recompiled (entry state) with its
    pictures embedded from the cache, except the one that shows \\thepage."""
    text = "\n\n".join(["Additional text to make the chapter longer. " * 40] * 8)
    edit(pictures / "chapters" / "plots.tex", "See Figure~", text + "\n\nSee Figure~")
    rep = checked(pictures, capsys)
    diagrams = [x for r in rep["runs"] for x in r["reasons"].get("chapters/diagrams", [])]
    assert any(x.startswith("entry state changed") for x in diagrams), diagrams
    assert [x for x in diagrams if x.startswith("pictures exported")] == [
        "pictures exported (1)"
    ], diagrams
