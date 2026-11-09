"""Edge cases: stale-output paths of the review (docs/review/M8.md, C1-C5).

Each build asserts §3.3 against ``--full`` (``--check``).
"""

import json
import os
from pathlib import Path

import pytest
from _helpers import build, checked, edit, reasons, selections

from chapmk.synctex import parse as parse_synctex

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


def test_local_packages_before_and_after_the_split(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """C1: a local package read by the format build (before the split point) and one read by
    the runs' preamble (after it) are global inputs: editing either gives a cold build with a
    new format, not a stale format or a glue-only run."""
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
        edit(path, old, new)
        rep = checked(src, capsys)
        assert rep["mode"] == "cold" and name in rep["reason"], rep


def test_list_file_with_another_extension(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """C2: \\listofalgorithms of algorithm.sty reads <job>.loa, an extension chapmk did not know.
    It is recorded, stored, spliced and kept fresh; a stale main.loa of a manual build in
    the source directory is not read."""
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
    edit(path, "Beta method", "Gamma method")
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

    dist, src = tmp_path / "texmf", tmp_path / "src"
    dist.mkdir()
    src.mkdir()
    monkeypatch.setenv("TEXINPUTS", f"{dist}//{os.pathsep}")
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
        edit(path, old, new)
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
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """book, openright: the blank page before a chapter shows the running head of the last
    section of the previous chapter. An excluded unit restores the marks its committing run
    recorded at its end; the marks are part of the state vector, so a changed last heading
    recompiles the following unit (entry state changed)."""
    src = tmp_path / "src"
    _heads_document(src)
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "b.tex"
    edit(path, "Text b.", "Txet b.")
    rep = checked(src, capsys)
    assert selections(rep) == [["b"]], rep["runs"]
    path = src / "a.tex"
    edit(path, "Sec a two", "Sec a TWO")
    rep = checked(src, capsys)
    b = reasons(rep, "b")
    assert any(x.startswith("entry state changed (marks 2e-right") for x in b), rep["runs"]


def _anchor_document(src: Path, cls: str, after: str, start: str = "") -> None:
    """Three units with sections and a figure; ``after``: main-file text after the last
    include; ``start``: the start of units b and c (default: a numbered chapter)."""
    src.mkdir()
    (src / "main.tex").write_text(
        f"\\documentclass[listof=totoc]{{{cls}}}\n\\usepackage{{lipsum}}\n"
        "\\usepackage{hyperref}\n\\usepackage{bookmark}\n\\begin{document}\n\\tableofcontents\n"
        f"\\include{{a}}\n\\include{{b}}\n\\include{{c}}\n{after}\n\\end{{document}}\n"
    )
    for x in "abc":
        head = start if start and x != "a" else f"\\chapter{{Chap {x}}}"
        (src / f"{x}.tex").write_text(
            f"{head}\n\\section{{First of {x}}}\nText {x}.\n\\lipsum[1-3]\n"
            f"\\begin{{figure}}[h]\\rule{{2cm}}{{1cm}}\\caption{{Fig {x}}}\\end{{figure}}\n"
            f"\\section{{Last of {x}}}\n\\lipsum[4-6]\n"
        )


def test_anchor_of_the_last_unit_used_after_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S19 (sweep C1): after the last \\include, KOMA's listof=totoc and a manual
    \\addcontentsline link to the last anchor of c (KOMA's \\chapter* sets none), \\label takes
    c's last number, also in a plain build. A run without c would use an older anchor: c is
    compiled in every run, with a warning and the fix. With \\phantomsection after the page
    break the main file has its own anchor: no warning, typos compile one unit."""
    src = tmp_path / "src"
    _anchor_document(
        src,
        "scrbook",
        "\\listoffigures\n\\cleardoublepage\n\\addcontentsline{toc}{chapter}{REFERENCES}"
        "\\label{refs}\nREFERENCES (\\ref{refs}, \\nameref{refs}).",
    )
    rep = checked(src, capsys)
    for line in ("main.tex:10: \\addcontentsline", "main.tex:12: \\addcontentsline"):
        assert any(
            w.startswith(line) and "c is compiled in every run" in w for w in rep["warnings"]
        )
    assert any(w.startswith("main.tex:12: \\label") for w in rep["warnings"]), rep["warnings"]
    edit(src / "a.tex", "Text a.", "Txet a.")
    assert selections(checked(src, capsys)) == [["a", "c"]]
    edit(
        src / "main.tex",
        "\\listoffigures\n\\cleardoublepage\n",
        "\\cleardoublepage\\phantomsection\n\\listoffigures\n\\cleardoublepage\\phantomsection\n",
    )
    edit(
        src / "main.tex", "\\label{refs}\nREFERENCES (\\ref{refs}, \\nameref{refs}).", "REFERENCES."
    )
    rep = checked(src, capsys)
    assert rep["mode"] == "cold" and not any("anchor" in w for w in rep["warnings"]), rep
    edit(src / "b.tex", "Text b.", "Txet b.")
    assert selections(checked(src, capsys)) == [["b"]]


def test_anchor_used_at_the_start_of_a_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S19: KOMA's \\chapter* sets no anchor, so an \\addcontentsline right after it at the
    start of b links to a's last anchor: a is compiled in every run. Sections renumbered after
    \\chapter* reuse a's anchor names; those are b's own. With \\phantomsection after
    \\chapter* (an edit of b only), a is a normal unit again."""
    src = tmp_path / "src"
    _anchor_document(src, "scrbook", "", "\\chapter*{Star}\\addcontentsline{toc}{chapter}{Star}")
    rep = checked(src, capsys)
    lines = sorted(
        w.split(":")[0] + ":" + w.split(":")[1] for w in rep["warnings"] if "anchor" in w
    )
    assert lines == ["b.tex:1", "c.tex:1"], rep["warnings"]
    edit(src / "c.tex", "Text c.", "Txet c.")
    assert selections(checked(src, capsys)) == [None]  # a and b are global: all units
    for x in "bc":
        edit(src / f"{x}.tex", "\\chapter*{Star}", "\\chapter*{Star}\\phantomsection")
    rep = checked(src, capsys)
    assert not any("anchor" in w for w in rep["warnings"]), rep["warnings"]
    edit(src / "c.tex", "Txet c.", "Text c.")
    assert selections(checked(src, capsys)) == [["c"]]


def test_contents_line_before_the_bibliography(
    thesis: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S19 (sweep C1): \\addcontentsline{toc}{chapter}{...} before \\printbibliography links
    to the last anchor of appB: appB is compiled in every run."""
    edit(
        thesis / "main.tex",
        "\\printbibliography\n",
        "\\cleardoublepage\n\\addcontentsline{toc}{chapter}{REFERENCES}\n\\printbibliography\n",
    )
    rep = checked(thesis, capsys)
    assert any("chapters/appB is compiled in every run" in w for w in rep["warnings"]), rep
    edit(thesis / "chapters" / "ch5.tex", "Further reading:", "Furhter reading:")
    rep = checked(thesis, capsys)
    assert selections(rep)[0] == ["chapters/ch5", "chapters/appB"], rep["runs"]


def test_primitive_marks_fall_back(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A primitive \\mark cannot be restored for excluded units: full mode with a warning."""
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
    tmp_path: Path, capsys: pytest.CaptureFixture[str], jobs: str
) -> None:
    """C13: an eqparbox tag used in two chapters with different widths. A partial run computes
    the width from its own boxes only, so a changed width of such a tag means a full build,
    with the reason; a tag used in one chapter stays incremental."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{eqparbox}\n\\begin{document}\n"
        "\\include{a}\n\\include{b}\n\\include{c}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}\\eqparbox{shared}{a very very wide box}|after\n")
    (src / "b.tex").write_text("\\chapter{B}\\eqparbox{shared}{narrow}|after\n\nText b.\n")
    (src / "c.tex").write_text("\\chapter{C}\\eqparbox{own}{only here}|after\n\nText c.\n")
    for edited in (False, True):  # cold build, then an edit of b
        if edited:
            edit(src / "b.tex", "Text b.", "Txet b.")
        rep = checked(src, capsys, "-j", jobs)  # §3.3 in any case
        # which units share a run depends on the run grouping (measured run times): either
        # the shared tag gave a full build, or a and b were last compiled in one run
        if rep["mode"] == "full":
            assert "eqparbox tag 'shared' is used in a, b" in rep["reason"], rep
            assert any("eqparbox tag 'shared'" in w for w in rep["warnings"]), rep
        else:
            state = json.loads((src / ".chapmk" / "main" / "canon" / "state.json").read_text())
            assert state["segments"]["U1"]["run"] == state["segments"]["U2"]["run"], rep
    # the shared tag in one chapter only: incremental again
    (src / "b.tex").write_text("\\chapter{B}\\eqparbox{bown}{narrow}|after\n\nText b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "c.tex"
    edit(path, "Text c.", "Txet c.")
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
    capsys: pytest.CaptureFixture[str],
    preamble: str,
    reason: str,
) -> None:
    """S13: immediate PDF objects (cmap's ToUnicode maps), colour stacks and catalog entries
    that cannot be recorded in the format part: full build with the reason."""
    src = tmp_path / "src"
    _format_state_document(src, preamble)
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "format build failed" in rep["reason"], rep
    assert reason in rep["reason"], rep


def test_catalog_and_info_of_the_format_part_are_replayed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S13: \\pdfcatalog and \\pdfinfo in the format part are recorded and replayed by every
    run (check compares the catalog and the document info)."""
    import pikepdf

    src = tmp_path / "src"
    _format_state_document(src, "\\pdfcatalog{/PageMode /UseThumbs}\\pdfinfo{/Keywords (k1)}")
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "b.tex"
    edit(path, "Text b.", "Txet b.")
    assert checked(src, capsys)["mode"] == "incremental"
    with pikepdf.open(src / "main.pdf") as pdf:
        assert pdf.Root.PageMode == "/UseThumbs" and str(pdf.docinfo["/Keywords"]) == "k1"


def test_open_action_when_the_document_starts_with_an_include(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """hyperref's ``/OpenAction`` (``goto page 1``) refers to the first page. With no page
    before the first ``\\include``, G0 has no pages and its run (the last one) may not have
    compiled the first unit: the catalog then came from a run whose page 1 is a later chapter
    (check: OpenAction on page 5 instead of 1). The catalog now comes from the run of the
    first page."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{report}\n\\usepackage{hyperref}\n\\usepackage{bookmark}\n"
        "\\begin{document}\n\\include{a}\n\\include{b}\n\\include{c}\n\\end{document}\n"
    )
    for name in "abc":
        (src / f"{name}.tex").write_text(f"\\chapter{{{name}}}Text {name}.\\clearpage Page 2.\n")
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "c.tex"
    edit(path, "Text c.", "Txet c.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and selections(rep) == [["c"]], rep


def test_first_page_material_when_the_first_unit_is_excluded(
    copy_corpus,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    """S15: the document starts with an \\include; a run of a later unit must not put the
    first-page material (hyperref's Doc-Start, xcolor's colour stack push, the
    shipout/firstpage hook) onto its first page: the SyncTeX records per page equal the
    --full reference's (§3.3 holds anyway: the material is invisible)."""
    src = copy_corpus("minimal/S15-first-page")
    assert checked(src, capsys)["mode"] == "cold"
    path = src / "c.tex"
    edit(path, "Text c.", "Txet c.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and selections(rep) == [["c"]], rep
    ref = parse_synctex(src / ".chapmk" / "main" / "check" / "main.synctex.gz")
    got = parse_synctex(src / "main.synctex.gz")
    assert [len(ref.sheets[n]) for n in sorted(ref.sheets)] == [
        len(got.sheets[n]) for n in sorted(got.sheets)
    ]


def test_nodes_left_on_the_main_vertical_list_are_replayed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """S13: xcolor leaves an unmatched \\pdfcolorstack push on the main vertical list of the
    format part, which a format does not dump. A colour left open in a textpos block of the
    title page (hgbthesis 2025/02/24) then reaches the next page in a plain build only. The
    format build keeps those nodes in a box that every run puts back: check passes, cold and
    incremental (it failed on page 2 before)."""
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
    edit(path, "Text b.", "Txet b.")
    assert checked(src, capsys)["mode"] == "incremental"


@pytest.mark.parametrize(
    "before",
    ["\\addtocontents{toc}{\\protect\\relax}", "\\selectlanguage{english}"],
)
def test_list_writes_before_the_first_include(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], before: str
) -> None:
    """S15: a deferred list-file write before the first \\include (\\addtocontents, babel's
    language record) reaches the list files at the first page shipped. A run that compiles
    the first unit ships it after the unit's entry record; the extra first page of a run that
    excludes the unit must too, else the write lands in the unit's list-file section and the
    self-check fails in every build that excludes the unit (full build, then cold)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage[ngerman,english]{babel}\n\\begin{document}\n"
        f"{before}\n\\include{{a}}\n\\include{{b}}\n\\tableofcontents\n\\include{{c}}\n"
        "\\end{document}\n"
    )
    (src / "a.tex").write_text("Title page.\n")
    (src / "b.tex").write_text("Verso.\n")
    (src / "c.tex").write_text("\\chapter{C}Text c.\n")
    rep = checked(src, capsys)
    assert rep["mode"] == "cold" and not any("full build" in w for w in rep["warnings"]), rep
    edit(src / "c.tex", "Text c.", "Txet c.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["c"], rep


def test_include_in_a_unit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """\\include in a unit's text (\\verb, verbatim: manuals that document \\include) is not a
    nested \\include: the build is incremental. A real nested \\include is LaTeX's error,
    reported with its location."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text(
        "\\chapter{A}Use \\verb|\\include{file}|.\n\\begin{verbatim}\n\\include{x}\n"
        "\\end{verbatim}\n"
    )
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["b"], rep
    (src / "x.tex").write_text("X.\n")
    edit(src / "b.tex", "Txet b.", "\\include{x}")
    rc, _ = build(src)
    err = capsys.readouterr().err
    assert rc == 1 and "b.tex:1: LaTeX Error: \\include cannot be nested" in err, err


@pytest.mark.parametrize("jobs", ["1", "4"])
def test_cleveref_across_units(
    copy_corpus,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
    jobs: str,
) -> None:
    """S16: \\cref, \\crefrange and \\cpageref across units; a changed number recompiles
    the referencing units; a change of only the cleveref type (\\label[type]{key}: key@cref)
    too (the reference prints "Theorem" instead of "Lemma")."""
    src = copy_corpus("minimal/S16-cleveref")
    assert checked(src, capsys, "-j", jobs)["mode"] == "cold"
    edit(src / "c.tex", "Text c.", "Txet c.")
    rep = checked(src, capsys, "-j", jobs)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["c"], rep
    edit(src / "b.tex", "Text b.", "Text b.\n\\begin{figure}[htb]B0\\caption{New}\\end{figure}")
    rep = checked(src, capsys, "-j", jobs)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["a", "b", "c"], rep
    edit(src / "c.tex", "\\label[lemma]{thm:alias}", "\\label[theorem]{thm:alias}")
    rep = checked(src, capsys, "-j", jobs)
    assert rep["mode"] == "incremental" and set(rep["compiled"]) == {"a", "c"}, rep


def test_biblatex_with_the_bibtex_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """biblatex with backend=bibtex passed in a configuration file (classicthesis does this):
    the preamble scan sees \\usepackage[backend=biber]{biblatex}, the run's aux names a BibTeX
    database (\\bibdata). Full build with the reason; full mode runs bibtex (latexmk does)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "config.tex").write_text("\\PassOptionsToPackage{backend=bibtex}{biblatex}\n")
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\input{config}\n\\usepackage[backend=biber]{biblatex}\n"
        "\\addbibresource{refs.bib}\n\\begin{document}\n\\include{a}\n\\include{b}\n"
        "\\printbibliography\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}See \\cite{knuth}.\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    (src / "refs.bib").write_text(
        "@book{knuth, author={Donald Knuth}, title={The TeXbook}, year={1984}, publisher={AW}}\n"
    )
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "BibTeX in use" in rep["reason"], rep
    assert "\\entry{knuth}" in (src / ".chapmk" / "main" / "full" / "main.bbl").read_text()


@pytest.mark.parametrize("jobs", ["1", "4"])
def test_mparhack_margin_notes(
    copy_corpus,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
    jobs: str,
) -> None:
    """S17: mparhack counts margin notes document-wide (a macro, not in the state vector) and
    records the count per page; a run compares its count only with its own records, so as
    self data the result equals a full build. Typos compile only their unit."""
    src = copy_corpus("minimal/S17-mparhack-acronym/mparhack")
    assert checked(src, capsys, "-j", jobs)["mode"] == "cold"
    edit(src / "a.tex", "Text a.", "Text a. \\marginpar{Extra 1}\\marginpar{Extra 2}")
    rep = checked(src, capsys, "-j", jobs)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["a"], rep
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys, "-j", jobs)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["b"], rep


def test_acronym_gives_full_builds(
    copy_corpus,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    """S17: acronym keeps the first use of each acronym in global macros, which a run that
    excludes the unit with the first use does not see (it printed the long form again):
    full builds with the reason."""
    src = copy_corpus("minimal/S17-mparhack-acronym/acronym")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "acronym" in rep["reason"], rep
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "acronym" in rep["reason"], rep


def test_page_colour_set_in_a_unit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """S18: \\pagecolor sets the page colour globally; a run that excludes the unit that set
    it gave later pages the default colour. The lint makes the unit global."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{xcolor}\n\\begin{document}\n"
        "\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Text a.\n\\pagecolor{yellow}\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)  # files are attributed (and linted) after the first run
    assert rep["mode"] == "incremental" and rep["compiled"] == ["a", "b"], rep
    assert any("a.tex:2: \\pagecolor" in w for w in rep["warnings"]), rep


@pytest.mark.parametrize("jobs", ["1", "4"])
def test_index_with_makeidx(tmp_path: Path, capsys: pytest.CaptureFixture[str], jobs: str) -> None:
    """makeidx: \\index entries carry page numbers; like nomencl, the canonical .idx holds
    each segment's entries from its committing run and makeindex runs in canon/. A typo
    compiles one unit; a new entry and a page shift change the index the glue prints."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage{makeidx}\n\\makeindex\n\\usepackage{lipsum}\n"
        "\\begin{document}\n\\include{a}\n\\include{b}\n\\include{c}\n\\printindex\n"
        "\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Alpha\\index{alpha}. Text a.\n\\lipsum[1-2]\n")
    (src / "b.tex").write_text("\\chapter{B}Beta\\index{beta} and alpha\\index{alpha}. Text b.\n")
    (src / "c.tex").write_text("\\chapter{C}Gamma\\index{gamma!sub}. Text c.\n")
    assert checked(src, capsys, "-j", jobs)["mode"] == "cold"
    edit(src / "c.tex", "Text c.", "Txet c.")
    rep = checked(src, capsys, "-j", jobs)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["c"], rep
    edit(src / "b.tex", "Text b.", "Delta\\index{delta}. Text b.")
    rep = checked(src, capsys, "-j", jobs)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["b"], rep
    assert "delta" in (src / ".chapmk" / "main" / "canon" / "main.ind").read_text()
    edit(src / "a.tex", "\\lipsum[1-2]", "\\lipsum[1-30]")  # b and c move by pages
    rep = checked(src, capsys, "-j", jobs)
    assert rep["mode"] == "incremental" and "a" in rep["compiled"], rep


@pytest.mark.parametrize(
    "switch",
    [
        "\\color{red}",
        "\\pdfrender{TextRenderingMode=Invisible}",
        "\\bfseries",
        "\\small",
        "\\raggedright",
        "\\linespread{1.6}\\selectfont",
    ],
)
def test_state_left_open_at_the_end_of_a_unit(
    copy_corpus,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
    switch: str,
) -> None:
    """S18: a state switch at the top level of a unit stays in effect for the next units; a
    run that excludes the unit started them in the default state (wrong output). The lint
    warns and makes the unit global: it is compiled with the later units."""
    src = copy_corpus("minimal/S18-unit-state")
    edit(src / "a.tex", "% end of a", switch)
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)  # files are attributed (and linted) after the first run
    assert rep["mode"] == "incremental" and rep["compiled"] == ["a", "b"], rep
    assert any("a.tex:3:" in w and "stays in effect" in w for w in rep["warnings"]), rep
