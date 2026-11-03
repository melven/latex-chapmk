"""R0.9 scenarios: stale-output paths of the M8 review (docs/review/M8.md, C1-C5).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path
from typing import Any

import pytest
from _helpers import EPOCH, build, selections

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


def test_list_file_with_another_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """C2: \\listofalgorithms of algorithm.sty reads <job>.loa, an extension chapmk did not know.
    It is recorded, stored, spliced and kept fresh; a stale main.loa of a manual build in
    the source directory is not read."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{algorithm}\n\\begin{document}\n"
        "\\listofalgorithms\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    for name, title in (("a", "Alpha"), ("b", "Beta")):
        (src / f"{name}.tex").write_text(
            f"\\chapter{{{name}}}\\begin{{algorithm}}x"
            f"\\caption{{{title} method}}\\end{{algorithm}}\n"
        )
    (src / "main.loa").write_text("\\contentsline {algorithm}{STALE ENTRY}{1}\n")
    assert checked(src, capsys)["mode"] == "cold"
    state = (src / ".chapmk" / "main" / "canon" / "state.json").read_text()
    assert '".loa"' in state
    path = src / "b.tex"
    path.write_text(path.read_text().replace("Beta method", "Gamma method"))
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental", rep
    loa = (src / ".chapmk" / "main" / "canon" / "main.loa").read_text()
    assert "Gamma method" in loa and "Beta" not in loa and "STALE" not in loa


def test_distribution_update_and_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """C4: packages outside the source directory (here via TEXINPUTS, standing in for a
    ``tlmgr`` update) read by the format build or by the runs force a cold build with a new
    format, so reused pages and new runs never mix package versions. A chapmk upgrade does
    too."""
    import chapmk

    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    dist, src = tmp_path / "texmf", tmp_path / "src"
    dist.mkdir()
    src.mkdir()
    monkeypatch.setenv("TEXINPUTS", f"{dist}//:")
    (dist / "distearly.sty").write_text("\\newcommand\\distearly{EARLY-1}\n")
    (dist / "distlate.sty").write_text("\\newcommand\\distlate{LATE-1}\n")
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{distearly}\n\\usepackage{distlate}\n"
        "\\begin{document}\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}\\distearly\\ \\distlate\n")
    (src / "b.tex").write_text("\\chapter{B}text\n")
    (src / "chapmk.toml").write_text('[format]\nsplit_before = ["usepackage\\\\{distlate\\\\}"]\n')
    assert checked(src, capsys)["mode"] == "cold"
    for name, old, new in (("distlate", "LATE-1", "LATE-22"), ("distearly", "EARLY-1", "EARLY-22")):
        path = dist / f"{name}.sty"
        path.write_text(path.read_text().replace(old, new))
        rep = checked(src, capsys)
        assert rep["mode"] == "cold" and f"{name}.sty" in rep["reason"], rep
    assert checked(src, capsys)["mode"] == "noop"
    monkeypatch.setattr(chapmk, "__version__", "99.0.0")
    rep = checked(src, capsys)
    assert rep["mode"] == "cold" and "chapmk version" in rep["reason"], rep


def _heads_document(src: Path, extra: str = "") -> None:
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{lipsum}\n\\begin{document}\n\\tableofcontents\n"
        "\\include{a}\n\\include{b}\n\\include{c}\n\\end{document}\n"
    )
    for x in "abc":  # a ends on page 5: blank page 6 before b (head of a's last section)
        n = 9 if x == "a" else 3
        (src / f"{x}.tex").write_text(
            f"\\chapter{{Chap {x}}}\n\\section{{Sec {x} one}}\n\\lipsum*[1-4]\n"
            f"\\section{{Sec {x} two}}\nText {x}.{extra if x == 'a' else ''}\n\\lipsum*[1-{n}]\n"
        )


def test_running_heads_of_excluded_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """book, openright: the blank page before a chapter shows the running head of the last
    section of the previous chapter. An excluded unit restores the marks its committing run
    recorded at its end; the marks are part of the state vector, so a changed last heading
    recompiles the following unit (entry state changed)."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    _heads_document(src)
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "b.tex"
    path.write_text(path.read_text().replace("Text b.", "Txet b."))
    rep = checked(src, capsys)
    assert selections(rep) == [["b"]], rep["runs"]
    path = src / "a.tex"
    path.write_text(path.read_text().replace("Sec a two", "Sec a TWO"))
    rep = checked(src, capsys)
    b = [x for r in rep["runs"] for x in r["reasons"].get("b", [])]
    assert any(x.startswith("entry state changed (marks 2e-right") for x in b), rep["runs"]


def test_primitive_marks_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A primitive \\mark cannot be restored for excluded units: full mode with a warning."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    _heads_document(src, "\\mark{raw}")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "primitive marks" in rep["reason"], rep
    assert any("primitive marks" in w for w in rep["warnings"]), rep
    # persistent (full-only.json): the next build skips the attempt, still with the warning
    runs = src / ".chapmk" / "main" / "runs"
    before = sorted(p.name for p in runs.iterdir())
    rep = checked(src, capsys)
    assert sorted(p.name for p in runs.iterdir()) == before  # no incremental run
    assert rep["mode"] == "full" and [r["name"] for r in rep["runs"]] == ["full"], rep
    assert any("primitive marks" in w for w in rep["warnings"]), rep
    assert (src / ".chapmk" / "main" / "canon" / "full-only.json").is_file()
