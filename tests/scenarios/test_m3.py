"""M3 scenarios (PLAN §8.2): T1, T14, T15, T17 on the thesis corpus; unit grouping on hgb.

Each scenario asserts §3.3 equality against --full (``fastinc build --check``) and the set of
compiled includes from ``--report``.
"""

import json
from pathlib import Path

import pytest

from fastinc.cli import main

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]
EPOCH = "1700000000"


def build(src: Path, *args: str) -> tuple[int, dict]:  # type: ignore[type-arg]
    report = src.parent / "report.json"
    report.unlink(missing_ok=True)
    rc = main(["build", "main.tex", "--report", str(report), *args], cwd=src)
    data = json.loads(report.read_text()) if report.is_file() else {}
    return rc, data


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


@pytest.fixture
def thesis(copy_corpus, monkeypatch: pytest.MonkeyPatch) -> Path:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src: Path = copy_corpus("thesis")
    rc, rep = build(src, "--check")
    assert rc == 0, rep
    assert rep["mode"] == "cold" and rep["reason"] == "no previous state"
    return src


def test_t1_typo_compiles_one_unit(thesis: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T1 (+T15, T17 via --check): typo in ch3 -> only ch3, no glue run, output equals --full."""
    # typo in body text after the \\todo (whose margin-note position is recorded)
    edit(thesis / "chapters" / "ch3.tex", "Further reading:", "Furhter reading:")
    rc, rep = build(thesis, "--check")
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert rep["mode"] == "incremental", rep
    assert rep["compiled"] == ["chapters/ch3"]
    assert [r["selection"] for r in rep["runs"]] == [["chapters/ch3"]]
    assert "PASS" in out.out and "synctex view" in out.out
    # nothing to do afterwards
    rc, rep = build(thesis)
    assert (rc, rep["mode"], rep["compiled"]) == (0, "noop", [])


def test_t14_syntax_error_keeps_previous_pdf(
    thesis: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = (thesis / "main.pdf").read_bytes()
    lines = (thesis / "chapters" / "ch4.tex").read_text().split("\n")
    lines.insert(4, "\\undefinedmacro")
    (thesis / "chapters" / "ch4.tex").write_text("\n".join(lines))
    capsys.readouterr()
    rc, _ = build(thesis)
    err = capsys.readouterr().err
    assert rc == 1
    assert "chapters/ch4.tex:5: Undefined control sequence" in err
    assert (thesis / "main.pdf").read_bytes() == pdf
    assert "Undefined control sequence" in (thesis / "main.log").read_text()
    # removing the error restores the canonical sources: nothing to compile, output correct
    lines.pop(4)
    (thesis / "chapters" / "ch4.tex").write_text("\n".join(lines))
    rc, rep = build(thesis, "--check")
    assert rc == 0 and rep["mode"] == "noop" and rep["compiled"] == []


def test_layout_change_falls_back_to_cold_build(thesis: Path) -> None:
    """M3 has no dependency model: a unit whose page count changes forces a cold build."""
    para = "\n\n".join(["Additional text to make the chapter longer. " * 40] * 6)
    edit(
        thesis / "chapters" / "ch2.tex",
        "\\section*{Remarks on ch2}",
        para + "\n\\section*{Remarks on ch2}",
    )
    rc, rep = build(thesis, "--check")
    assert rc == 0 and rep["mode"] == "cold" and "chapters/ch2" in rep["reason"]


def test_compilation_unit_grouping_hgb(
    copy_corpus,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = copy_corpus("hgb")
    assert build(src)[0] == 0
    edit(src / "chapters" / "usage_details.tex", "param_7 & m", "param_7 & mm")
    rc, rep = build(src, "--check")
    out = capsys.readouterr()
    assert rc == 0, out.out
    assert rep["mode"] == "incremental"
    assert rep["compiled"] == ["chapters/usage", "chapters/usage_details"]
