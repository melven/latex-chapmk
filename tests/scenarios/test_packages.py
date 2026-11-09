"""Packages with their own handling: eqparbox (C13), cleveref (S16), biblatex with the
BibTeX backend, mparhack (S17), acronym and perpage (full mode), makeidx.

Each build asserts §3.3 against ``--full`` (``--check``).
"""

import json
from pathlib import Path

import pytest
from _helpers import checked, edit

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


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


def test_footmisc_perpage_builds_in_full_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """footmisc's perpage option loads perpage.sty: counters reset per page through aux data
    and \\c@pabs@page, a macro posing as a counter. Incremental builds failed (unreadable
    records, then wrong page numbers; sweep: BernhardMarconato/computer-vision-exercises),
    so the package is unsupported: full mode with a warning, also after an edit."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass{book}\n\\usepackage[perpage]{footmisc}\n\\begin{document}\n"
        "\\include{a}\n\\include{b}\n\\include{c}\n\\end{document}\n"
    )
    for name in "abc":
        notes = "".join(f"Text {name}{k}.\\footnote{{Note {name}{k}.}}\n\n" for k in range(40))
        (src / f"{name}.tex").write_text(f"\\chapter{{{name.upper()}}}\n{notes}")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "'perpage'" in rep["reason"], rep
    edit(src / "b.tex", "Text b3.", "Txet b3.")
    rep = checked(src, capsys)
    assert rep["mode"] == "full" and "'perpage'" in rep["reason"], rep


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
