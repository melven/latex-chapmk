"""R0.9 robustness scenarios (docs/review/M8.md, C6-C9): interrupted builds, signals, errors.

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path
from typing import Any

import pytest
from _helpers import EPOCH, build, edit

import chapmk.incremental
from chapmk.cli import main

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def checked(src: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    rc, rep = build(src, "--check")
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "PASS" in out.out, out.out
    return rep


def _document(src: Path) -> None:
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n\\tableofcontents\n"
        "\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}\\label{a}Alpha, see \\ref{b}.\n")
    (src / "b.tex").write_text("\\chapter{B}\\label{b}Beta, see \\ref{a}.\n")


def test_interrupted_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """C7: a build killed while committing (after commit_run, before the state is saved)
    leaves the journal; a canonical file it truncated is never read: the next build is cold
    and equals --full."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    _document(src)
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "a.tex", "Alpha", "Alpha2")

    def killed(*_args: Any, **_kwargs: Any) -> bool:
        raise KeyboardInterrupt

    with monkeypatch.context() as m:
        m.setattr(chapmk.incremental, "commit_lists", killed)
        with pytest.raises(KeyboardInterrupt):
            main(["build", "main.tex"], cwd=src)
    canon = src / ".chapmk" / "main" / "canon"
    assert (canon / ".in-progress").exists()
    aux = canon / "a.aux"
    aux.write_bytes(aux.read_bytes()[:20])  # e.g. a kill during a non-atomic write
    rep = checked(src, capsys)
    assert rep["mode"] == "cold" and "interrupted" in rep["reason"], rep
    assert not (canon / ".in-progress").exists()


def test_interrupted_full_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """C7: a full build killed during a pass may leave truncated aux files; the next full
    build starts from an empty full-mode directory."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    _document(src)
    assert main(["build", "main.tex", "--full"], cwd=src) == 0
    full = src / ".chapmk" / "main" / "full"
    (full / ".in-progress").write_text("")
    (full / "a.aux").write_text("\\relax\n\\newlabel{a}{{1}{")  # truncated
    rc = main(["build", "main.tex", "--full"], cwd=src)
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert not (full / ".in-progress").exists()
