"""Static analysis of the third-party pgf manual corpus (tests/corpus/pgfmanual, no TeX)."""

import importlib.util
import shutil
from pathlib import Path

from fastinc.analysis import analyse
from fastinc.config import Config

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "pgfmanual"


def load_adapt():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("pgf_adapt", CORPUS / "adapt.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upstream_main_allows_only_full_builds() -> None:
    a = analyse(Config(main=CORPUS / "upstream" / "pgfmanual.tex"))
    assert a.includes == () and a.fallback_reasons


def test_adapted_main(tmp_path: Path) -> None:
    src = tmp_path / "src"
    shutil.copytree(CORPUS / "upstream", src)
    main = load_adapt().adapt(src)
    a = analyse(Config(main=main))
    assert a.fallback_reasons == ()
    assert len(a.includes) == 123
    assert len(a.units) == 123  # ltxdoc (no \chapter): each \section include is a unit
    assert "fastinc adapt" in main.read_text()
    # the upstream files are untouched
    for f in (CORPUS / "upstream").rglob("*.tex"):
        assert (src / f.relative_to(CORPUS / "upstream")).read_bytes() == f.read_bytes()
