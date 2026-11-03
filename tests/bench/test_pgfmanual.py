"""Stress test on the third-party pgf manual (tests/corpus/pgfmanual). Manual only (bench):
a full-mode build takes about 15 minutes."""

import importlib.util
import time
from pathlib import Path

import pytest

from chapmk.cli import main

pytestmark = [pytest.mark.bench, pytest.mark.slow]
CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "pgfmanual"


def adapt(src: Path) -> Path:
    spec = importlib.util.spec_from_file_location("pgf_adapt", CORPUS / "adapt.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result: Path = module.adapt(src)
    return result


@pytest.mark.parametrize("variant", ["upstream", "adapted"])
def test_full_build(copy_corpus, tmp_path: Path, variant: str) -> None:  # type: ignore[no-untyped-def]
    src = copy_corpus("pgfmanual/upstream")
    main_tex = adapt(src).name if variant == "adapted" else "pgfmanual.tex"
    start = time.monotonic()
    assert main(["build", main_tex, "--full", "--out-dir", str(tmp_path / "out")], cwd=src) == 0
    print(f"{variant}: full build {time.monotonic() - start:.0f} s")
