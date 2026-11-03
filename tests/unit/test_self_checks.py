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
    old = "\\chapmk@lmark {U1}\na\n\\chapmk@lmark {/U1}\n\\chapmk@lmark {U2}\nb\n\\chapmk@lmark {/U2}\n"
    new = old.replace("\na\n", "\nA\n")
    _check_kept_sections(new, old, {"U2"}, "main.toc")  # U1 was compiled: may change
    _check_kept_sections(new, "", {"U1"}, "main.toc")  # no previous section: nothing to check
    with pytest.raises(SelfCheckError, match=r"main.toc: the entries of U1"):
        _check_kept_sections(new, old, {"U1", "U2"}, "main.toc")
