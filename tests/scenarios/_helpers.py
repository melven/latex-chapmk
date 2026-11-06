"""Scenario helpers (design §8.2): builds with ``--report``, source edits of the corpora and
queries of the report."""

import json
from pathlib import Path
from typing import Any

import pytest

from chapmk.cli import main

#: ``chapmk build --report`` as JSON
Report = dict[str, Any]

#: the includes of the thesis corpus, in document order
THESIS_UNITS = [f"chapters/ch{k}" for k in range(1, 7)] + ["chapters/appA", "chapters/appB"]
#: text that makes a thesis chapter several pages longer
LONG_TEXT = "\n\n".join(["Additional text to make the chapter longer. " * 40] * 6)


def build(src: Path, *args: str) -> tuple[int, Report]:
    """``chapmk build main.tex`` with a JSON report; returns the exit code and the report."""
    report = src.parent / "report.json"
    report.unlink(missing_ok=True)
    rc = main(["build", "main.tex", "--report", str(report), *args], cwd=src)
    data = json.loads(report.read_text()) if report.is_file() else {}
    return rc, data


def checked(src: Path, capsys: pytest.CaptureFixture[str], *args: str) -> Report:
    """``chapmk build --check``: asserts success and §3.3 equality with ``--full``."""
    rc, rep = build(src, "--check", *args)
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "PASS" in out.out, out.out
    return rep


def edit(path: Path, old: str, new: str) -> None:
    """Replace the first ``old`` in a file; ``old`` must occur (a test must not pass because
    its edit silently did nothing)."""
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


def chapter(thesis: Path, name: str) -> Path:
    """A chapter file of the thesis corpus (``ch3``, ``appA``)."""
    return thesis / "chapters" / f"{name}.tex"


def lengthen(thesis: Path, name: str) -> None:
    """Make a thesis chapter several pages longer (before its remarks section)."""
    remarks = f"\\section*{{Remarks on {name}}}"
    edit(chapter(thesis, name), remarks, f"{LONG_TEXT}\n{remarks}")


def selections(rep: Report) -> list[list[str] | None]:
    """The selection of each run (None: all units)."""
    return [r["selection"] for r in rep["runs"]]


def batches(rep: Report) -> list[list[list[str] | None]]:
    """The selections of the runs per batch, in batch order."""
    out: dict[int, list[list[str] | None]] = {}
    for r in rep["runs"]:
        out.setdefault(r["batch"], []).append(r["selection"])
    return [out[k] for k in sorted(out)]


def reasons(rep: Report, unit: str | None = None) -> list[str]:
    """The compile reasons of all runs, of all units or of one."""
    return [
        x
        for r in rep["runs"]
        for u, rs in r["reasons"].items()
        if unit is None or u == unit
        for x in rs
    ]


def mispredictions(rep: Report) -> list[str]:
    return [x for x in reasons(rep) if x.startswith("misprediction")]


def run_with(rep: Report, arg: str) -> dict[str, Any]:
    """The first run of the report that compiled ``arg``."""
    for r in rep["runs"]:
        if r["selection"] is None or arg in r["selection"]:
            return r
    raise AssertionError(f"{arg} not compiled: {selections(rep)}")
