"""Runtime self-checks (docs/review/M8.md C14): inconsistencies fall back to full mode."""

from pathlib import Path

import pytest

from chapmk.canon import _check_bcf, _check_kept_sections
from chapmk.errors import FallbackError, SelfCheckError

BCF = (
    '<bcf:controlfile version="3.11">\n'
    '  <bcf:section number="0">\n'
    '    <bcf:citekey order="1" intorder="1">a</bcf:citekey>\n'
    '    <bcf:citekey order="2" intorder="1">b</bcf:citekey>\n'
    "  </bcf:section>\n"
    "</bcf:controlfile>\n"
)


def test_bcf_check(tmp_path: Path) -> None:
    """(a) the patched .bcf of a batch with a run of all units equals that run's .bcf."""
    written = tmp_path / "main.bcf"
    written.write_text(BCF)
    _check_bcf(BCF, written)
    _check_bcf(BCF, tmp_path / "missing.bcf")  # no .bcf (no biblatex): nothing to check
    with pytest.raises(SelfCheckError, match="citations differ") as err:
        _check_bcf(BCF.replace(">b<", ">c<"), written)
    assert isinstance(err.value, FallbackError) and "please report" in str(err.value)


def test_kept_list_sections() -> None:
    """(b) a unit no run of the batch compiled keeps its list entries."""
    old = (
        "\\chapmk@lmark {U1}\na\n\\chapmk@lmark {/U1}\n"
        "\\chapmk@lmark {U2}\nb\n\\chapmk@lmark {/U2}\n"
    )
    new = old.replace("\na\n", "\nA\n")
    _check_kept_sections(new, old, {"U2"}, "main.toc")  # U1 was compiled: may change
    _check_kept_sections(new, "", {"U1"}, "main.toc")  # no previous section: nothing to check
    with pytest.raises(SelfCheckError, match=r"main.toc: the entries of U1"):
        _check_kept_sections(new, old, {"U1", "U2"}, "main.toc")


def _run_pdf(path: Path, style: str) -> None:
    import pikepdf

    pdf = pikepdf.new()
    for _ in range(2):
        pdf.add_blank_page()
    nums = pikepdf.Array([0, pikepdf.Dictionary(S=pikepdf.Name(style))])
    pdf.Root.PageLabels = pikepdf.Dictionary(Nums=nums)
    pdf.save(path)


def test_page_label_check(tmp_path: Path) -> None:
    """(c) the merged labels (inferred from the \\thepage records) equal the run's own; pages
    after an extra picture page are not checked."""
    from chapmk.merge_pdf import PageSource, merge_pdf

    run = tmp_path / "r1.pdf"
    _run_pdf(run, "/r")  # the run's labels: i, ii
    pages = [PageSource(run, i, i + 1, ["i", "ii"][i]) for i in range(2)]
    merge_pdf(pages, [], run, tmp_path / "ok.pdf")
    wrong = [PageSource(run, i, i + 1, str(i + 1)) for i in range(2)]  # records say 1, 2
    with pytest.raises(SelfCheckError, match="page 1: merged page label '1'"):
        merge_pdf(wrong, [], run, tmp_path / "bad.pdf")
    unchecked = [PageSource(run, i, i + 1, str(i + 1), check_label=False) for i in range(2)]
    merge_pdf(unchecked, [], run, tmp_path / "unchecked.pdf")
