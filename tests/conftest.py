"""Shared fixtures. Tests marked ``slow`` need TeX Live on PATH (dev container)."""

import json
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


THESIS_EPOCH = "1700000000"


@pytest.fixture(scope="session")
def thesis_template(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, Path]]:
    """(live source dir, cache dir): the thesis corpus after a cold build with --check,
    built once per session. Restored copies live at the same absolute path: the shadow tree
    (symlinks), run directories and SyncTeX files contain absolute paths."""
    from fastinc.cli import main

    base = tmp_path_factory.mktemp("thesis")
    live, cache = base / "live" / "src", base / "cache"
    shutil.copytree(CORPUS / "thesis", live, ignore=shutil.ignore_patterns("generate.py"))
    prepare_figures(live)
    old = os.environ.get("SOURCE_DATE_EPOCH")
    os.environ["SOURCE_DATE_EPOCH"] = THESIS_EPOCH
    report = base / "live" / "report.json"
    try:
        rc = main(["build", "main.tex", "--check", "--report", str(report)], cwd=live)
    finally:
        if old is None:
            del os.environ["SOURCE_DATE_EPOCH"]
        else:
            os.environ["SOURCE_DATE_EPOCH"] = old
    rep = json.loads(report.read_text())
    assert rc == 0, rep
    assert rep["mode"] == "cold" and rep["reason"] == "no previous state"
    shutil.copytree(live, cache, symlinks=True)
    yield live, cache


@pytest.fixture
def thesis(thesis_template: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> Path:
    """A freshly restored, built thesis corpus (same absolute path in every test)."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", THESIS_EPOCH)
    live, cache = thesis_template
    shutil.rmtree(live)
    shutil.copytree(cache, live, symlinks=True)
    return live
