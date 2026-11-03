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
        assert main(["build", "main.tex"], cwd=src) == 130  # Ctrl-C (C8)
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


def _processes_mentioning(text: str) -> list[str]:
    """Command lines of running TeX processes that mention ``text``."""
    out = []
    for cmd in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            argv = cmd.read_bytes().decode(errors="replace").split("\0")
        except OSError:
            continue
        if argv and "tex" in Path(argv[0]).name and text in " ".join(argv):
            out.append(" ".join(argv))
    return out


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="needs /proc (Linux)")
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGINT"])
def test_signal_kills_children(tmp_path: Path, sig: str) -> None:
    """C8: SIGTERM (an editor stopping a build) or Ctrl-C kills the pdflatex processes of the
    build and exits with 143/130; no orphan keeps writing into the run directories."""
    import os
    import signal
    import subprocess
    import sys
    import time

    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}A\n")
    (src / "b.tex").write_text("\\chapter{B}\\loop\\iftrue\\repeat\n")  # runs until killed
    env = {
        **os.environ,
        "SOURCE_DATE_EPOCH": EPOCH,
        "PYTHONPATH": str(Path(chapmk.incremental.__file__).parents[1]),
    }
    p = subprocess.Popen([sys.executable, "-m", "chapmk", "build", "main.tex"], cwd=src, env=env)
    runs = src / ".chapmk" / "main" / "runs"
    deadline = time.monotonic() + 60
    while not list(runs.glob("*/main.log")) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert list(runs.glob("*/main.log")), "pdflatex did not start"
    time.sleep(0.5)
    assert _processes_mentioning(str(runs))
    p.send_signal(getattr(signal, sig))
    assert p.wait(30) == (143 if sig == "SIGTERM" else 130)
    assert _processes_mentioning(str(runs)) == []


def test_fallback_uses_the_state_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """C11: a fallback full build days after the cold build uses the dates of the canonical
    state, like --full and the check reference (no spurious \\today difference)."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    _document(src)
    edit(src / "a.tex", "Alpha,", "Alpha (\\today),")
    assert checked(src, capsys)["mode"] == "cold"
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(int(EPOCH) + 5 * 86400))
    edit(src / "main.tex", "\\begin{document}", "\\usepackage{cleveref}\n\\begin{document}")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "cleveref" in rep["reason"], rep


@pytest.mark.parametrize("mode", [(), ("--full",)])
def test_biber_error_is_shown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: tuple[str, ...],
) -> None:
    """E7: a broken .bib: exit code 2 with biber's error lines, in both builders."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage[backend=biber]{biblatex}\n"
        "\\addbibresource{refs.bib}\n\\begin{document}\n\\include{a}\n"
        "\\printbibliography\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}See \\cite{k1}.\n")
    (src / "refs.bib").write_text(
        "@book{k1,\n  title = {T},\n  author = {A, B,\n  year = 2000\n}\n"
    )
    assert main(["build", "main.tex", *mode], cwd=src) == 2
    err = capsys.readouterr().err
    assert "biber failed" in err and "syntax error" in err and "main.blg" in err, err
