"""Full-mode build and CLI against real TeX."""

from pathlib import Path

import pytest

from fastinc.cli import main
from fastinc.synctex import read_lines

pytestmark = pytest.mark.slow


def test_full_build_with_biber_and_nomencl(copy_corpus, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    src = copy_corpus("minimal/S1-format")
    out = tmp_path / "out"
    rc = main(["build", "main.tex", "--full", "--out-dir", str(out), "-v"], cwd=src)
    err = capsys.readouterr().err
    assert rc == 0, err
    assert (out / "main.pdf").is_file() and (out / "main.log").is_file()
    full = src / ".fastinc" / "full"
    assert (full / "main.bbl").is_file() and (full / "main.nls").is_file()
    assert "stable" in err and "pass 1: changed" in err
    inputs = [line for line in read_lines(out / "main.synctex.gz") if line.startswith("Input:")]
    assert any(line.endswith(f"{src}/./main.tex") for line in inputs), inputs[:3]
    assert not any(".fastinc/src" in line for line in inputs)
    assert ".fastinc/src" not in (out / "main.log").read_text()
    # nothing was written into the source directory except the build dir
    assert {p.name for p in src.iterdir()} == {"main.tex", "thesis.bib", "run.sh", ".fastinc"}


def test_failing_build_keeps_previous_pdf(copy_corpus, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    src = tmp_path / "s"
    src.mkdir()
    (src / "d.tex").write_text("\\documentclass{article}\n\\begin{document}\nok\n\\end{document}\n")
    assert main(["build", "d.tex"], cwd=src) == 0
    pdf = (src / "d.pdf").read_bytes()
    (src / "d.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\undefinedmacro\n\\end{document}\n"
    )
    assert main(["build", "d.tex"], cwd=src) == 1
    err = capsys.readouterr().err
    # pdfTeX reports paths relative to its cwd (the shadow tree = the source directory)
    assert "./d.tex:3: Undefined control sequence" in err
    assert (src / "d.pdf").read_bytes() == pdf
    assert "Undefined control sequence" in (src / "d.log").read_text()


def test_clean(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "d.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}\n")
    assert main(["build", "d.tex"], cwd=src) == 0
    assert (src / ".fastinc").is_dir()
    assert main(["clean", "d.tex"], cwd=src) == 0
    assert not (src / ".fastinc").exists()
    (src / "other").mkdir()
    assert main(["clean", "d.tex", "--build-dir", "other"], cwd=src) == 2
    assert (src / "other").is_dir()
