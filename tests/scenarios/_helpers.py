"""Scenario helpers (PLAN §8.2): builds with ``--report`` and source edits."""

import json
from pathlib import Path
from typing import Any

from chapmk.cli import main

EPOCH = "1700000000"


def build(src: Path, *args: str, main_file: str = "main.tex") -> tuple[int, dict[str, Any]]:
    """``chapmk build`` with a JSON report; returns the exit code and the report."""
    report = src.parent / "report.json"
    report.unlink(missing_ok=True)
    rc = main(["build", main_file, "--report", str(report), *args], cwd=src)
    data = json.loads(report.read_text()) if report.is_file() else {}
    return rc, data


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


def selections(rep: dict[str, Any]) -> list[list[str] | None]:
    return [r["selection"] for r in rep["runs"]]
