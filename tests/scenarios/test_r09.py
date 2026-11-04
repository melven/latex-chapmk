"""R0.9 scenarios: stale-output paths of the M8 review (docs/review/M8.md, C1-C5).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from _helpers import EPOCH, build, selections

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def checked(src: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    rc, rep = build(src, "--check", *args)
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


@pytest.mark.parametrize("jobs", ["1", "4"])
def test_eqparbox_tag_shared_by_chapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], jobs: str
) -> None:
    """C13: an eqparbox tag used in two chapters with different widths. A partial run computes
    the width from its own boxes only, so a changed width of such a tag means a full build,
    with the reason; a tag used in one chapter stays incremental."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{eqparbox}\n\\begin{document}\n"
        "\\include{a}\n\\include{b}\n\\include{c}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}\\eqparbox{shared}{a very very wide box}|after\n")
    (src / "b.tex").write_text("\\chapter{B}\\eqparbox{shared}{narrow}|after\n\nText b.\n")
    (src / "c.tex").write_text("\\chapter{C}\\eqparbox{own}{only here}|after\n\nText c.\n")
    for _ in range(2):  # cold build, then an edit of b
        rep = checked(src, capsys, "-j", jobs)  # §3.3 in any case
        # which units share a run depends on the run grouping (measured run times): either
        # the shared tag gave a full build, or a and b were last compiled in one run
        if rep["mode"] == "full":
            assert "eqparbox tag 'shared' is used in a, b" in rep["reason"], rep
            assert any("eqparbox tag 'shared'" in w for w in rep["warnings"]), rep
        else:
            state = json.loads((src / ".chapmk" / "main" / "canon" / "state.json").read_text())
            assert state["segments"]["U1"]["run"] == state["segments"]["U2"]["run"], rep
        path = src / "b.tex"
        path.write_text(path.read_text().replace("Text b.", "Txet b."))
    # the shared tag in one chapter only: incremental again
    (src / "b.tex").write_text("\\chapter{B}\\eqparbox{bown}{narrow}|after\n\nText b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "c.tex"
    path.write_text(path.read_text().replace("Text c.", "Txet c."))
    assert checked(src, capsys)["mode"] == "incremental"


def _format_state_document(src: Path, preamble: str) -> None:
    src.mkdir()
    (src / "main.tex").write_text(
        f"\\documentclass{{book}}\n{preamble}\n\\usepackage{{amsmath}}\n\\begin{{document}}\n"
        "\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Text $x^2 + \\alpha$.\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")


@pytest.mark.parametrize(
    ("preamble", "reason"),
    [
        ("\\usepackage{cmap}", "writes PDF objects immediately"),
        ("\\chardef\\mystack=\\pdfcolorstackinit page direct{0 g 0 G}", "creates colour stacks"),
        ("\\def\\kw{(k)}\\pdfinfo\\expandafter{\\expandafter/Keywords\\kw}", "without a braced"),
    ],
)
def test_state_a_format_loses_gives_a_full_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    preamble: str,
    reason: str,
) -> None:
    """S13: immediate PDF objects (cmap's ToUnicode maps), colour stacks and catalog entries
    that cannot be recorded in the format part: full build with the reason."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    _format_state_document(src, preamble)
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "format build failed" in rep["reason"], rep
    assert reason in rep["reason"], rep


def test_catalog_and_info_of_the_format_part_are_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S13: \\pdfcatalog and \\pdfinfo in the format part are recorded and replayed by every
    run (check compares the catalog and the document info)."""
    import pikepdf

    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    _format_state_document(src, "\\pdfcatalog{/PageMode /UseThumbs}\\pdfinfo{/Keywords (k1)}")
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "b.tex"
    path.write_text(path.read_text().replace("Text b.", "Txet b."))
    assert checked(src, capsys)["mode"] == "incremental"
    with pikepdf.open(src / "main.pdf") as pdf:
        assert pdf.Root.PageMode == "/UseThumbs" and str(pdf.docinfo["/Keywords"]) == "k1"


def test_nodes_left_on_the_main_vertical_list_are_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """S13: xcolor leaves an unmatched \\pdfcolorstack push on the main vertical list of the
    format part, which a format does not dump. A colour left open in a textpos block of the
    title page (hgbthesis 2025/02/24) then reaches the next page in a plain build only. The
    format build keeps those nodes in a box that every run puts back: check passes, cold and
    incremental (it failed on page 2 before)."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{xcolor}\n\\usepackage[absolute]{textpos}\n"
        "\\setlength{\\TPHorizModule}{10mm}\n\\setlength{\\TPVertModule}{10mm}\n"
        "\\begin{document}\n\\begin{titlepage}\n\\begin{textblock}{15}(3,25)\n"
        "\\centering\n\\color{red}No advisor(s) specified!\\\\\n\\end{textblock}\n\\null\n"
        "\\end{titlepage}\nText on the page after the title page.\n"
        "\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Text a.\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "b.tex"
    path.write_text(path.read_text().replace("Text b.", "Txet b."))
    assert checked(src, capsys)["mode"] == "incremental"
