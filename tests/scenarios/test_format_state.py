"""State a format does not keep (design §6.3.3, S13) and the first page of the document
(S15): catalog and info entries, nodes on the main vertical list, \\prevdepth, the
first page when the first unit is excluded.

Each build asserts §3.3 against ``--full`` (``--check``).
"""

from pathlib import Path

import pytest
from _helpers import checked, edit, selections

from chapmk.synctex import parse as parse_synctex

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]


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


@pytest.mark.parametrize("preamble", ["", "\\makeatletter\\def\\x@y{}\\makeatother\n"])
def test_vspace_star_right_after_begin_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], preamble: str
) -> None:
    """\\vspace* restores \\prevdepth, so the interline glue of the next line depends on the
    \\prevdepth the preamble left. A format does not dump it: runs started with -1000pt
    ("ignore depth"), the title page lost its 1pt \\lineskip glue and every line below was
    1pt higher (sweep: ary1002, alorenzo175 by 1-4.7pt). With \\makeatother at the end of the
    preamble, the format build did not capture the main vertical list at all (S13; mylatexformat
    reads the preamble with @ a letter; sweep: tscheffl/ThinkC)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        f"\\documentclass{{book}}\n{preamble}\\begin{{document}}\n\\thispagestyle{{empty}}\n"
        "\\vspace*{2.5in}{\\huge Title}\\par\\vspace{1in}{\\Large Author}\\clearpage\n"
        "\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}Text a.\n")
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    rep = checked(src, capsys)
    assert rep["mode"] == "incremental" and rep["compiled"] == ["b"], rep


def test_split_point_inside_a_package_conditional(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deny match inside a package's conditional (\\makeindex inside iftex's \\ifpdf, as in
    the D1 sweep templates): the format part ends before the conditional, not inside it."""
    src = tmp_path / "src"
    _format_state_document(
        src,
        "\\usepackage{iftex}\n\\ifpdf\n  \\usepackage{makeidx}\\makeindex\n\\else\n\\relax\n\\fi",
    )
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    assert checked(src, capsys)["compiled"] == ["b"]


def test_fonts_are_set_up_after_the_begin_document_hooks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sweep B2: mathptmx redeclares the AMS symbol fonts in \\AtBeginDocument (msam10 at all
    sizes), type1cm declares msam7 for 7-10pt. A plain build sets up the script size at the
    first formula, after that hook; the format must not set it up before (mylatexformat's font
    preloading), or the superscript \\intercal is 0.74pt wider."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(
        "\\documentclass[11pt]{book}\n\\usepackage{amssymb}\n\\usepackage{mathptmx}\n"
        "\\usepackage{type1cm}\n\\begin{document}\n\\include{a}\n\\include{b}\n"
        "\\end{document}\n"
    )
    (src / "a.tex").write_text(
        "\\chapter{A}Text a.\n\\begin{equation}\\hat S = w^\\intercal Z\\end{equation}\n"
    )
    (src / "b.tex").write_text("\\chapter{B}Text b.\n")
    assert checked(src, capsys)["mode"] == "cold"
    edit(src / "b.tex", "Text b.", "Txet b.")
    assert checked(src, capsys)["compiled"] == ["b"]
