"""Shared fixtures. Tests marked ``slow`` need TeX Live on PATH (dev container)."""

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "tests" / "corpus"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("pdflatex"):
        return
    skip = pytest.mark.skip(reason="pdflatex not on PATH (run inside the dev container)")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def copy_corpus(tmp_path: Path) -> Iterator["CorpusCopier"]:
    yield CorpusCopier(tmp_path)


class CorpusCopier:
    """Copies a corpus directory to a temporary source directory (never build in the repo)."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path

    def __call__(self, name: str, dest: str = "src") -> Path:
        target = self.tmp_path / dest
        shutil.copytree(CORPUS / name, target, ignore=shutil.ignore_patterns("generate.py"))
        prepare_figures(target)
        return target


def prepare_figures(src: Path) -> None:
    """Compile ``fig/*.tex`` (standalone sources) to ``fig/*.pdf`` in a corpus copy."""
    for tex in sorted(src.glob("fig/*.tex")):
        subprocess.run(
            ["pdflatex", "-interaction=batchmode", "-halt-on-error", tex.name],
            cwd=tex.parent,
            env=dict(os.environ),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        for ext in (".aux", ".log"):
            tex.with_suffix(ext).unlink(missing_ok=True)
