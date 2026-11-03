"""R0.9 scenarios: stale-output paths of the M8 review (docs/review/M8.md, C1-C5).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path
from typing import Any

import pytest
from _helpers import EPOCH, build

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def checked(src: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    rc, rep = build(src, "--check")
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "PASS" in out.out, out.out
    return rep


def test_local_packages_before_and_after_the_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """C1: a local package read by the format build (before the split point) and one read by
    the runs' preamble (after it) are global inputs: editing either gives a cold build with a
    new format, not a stale format or a glue-only run."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{early}\n\\usepackage{late}\n"
        "\\begin{document}\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "early.sty").write_text("\\newcommand\\early{EARLY-1}\n")
    (src / "late.sty").write_text("\\newcommand\\late{LATE-1}\n")
    (src / "a.tex").write_text("\\chapter{A}\\early\\ \\late\n")
    (src / "b.tex").write_text("\\chapter{B}text\n")
    (src / "chapmk.toml").write_text('[format]\nsplit_before = ["usepackage\\\\{late\\\\}"]\n')
    assert checked(src, capsys)["mode"] == "cold"
    for name, old, new in (("late.sty", "LATE-1", "LATE-2"), ("early.sty", "EARLY-1", "EARLY-2")):
        path = src / name
        path.write_text(path.read_text().replace(old, new))
        rep = checked(src, capsys)
        assert rep["mode"] == "cold" and name in rep["reason"], rep
