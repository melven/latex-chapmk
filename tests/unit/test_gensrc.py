from pathlib import Path

from fastinc.analysis import analyse
from fastinc.config import Config
from fastinc.gensrc import format_source, full_mode_input, run_main, write_if_changed
from fastinc.texsource import split_lines


def project(tmp_path: Path, newline: str = "\n") -> Config:
    (tmp_path / "a.tex").write_text("\\chapter{A}\n")
    text = (
        "\\documentclass{book}\n"
        "\\usepackage{tikz}\n"
        "\\tikzexternalize\n"
        "\\newcommand\\x{x}\n"
        "\\begin{document}\n"
        "\\include{a}\n"
        "\\end{document}\n"
    )
    main = tmp_path / "doc.tex"
    main.write_bytes(text.replace("\n", newline).encode())
    return Config(main=main)


def test_format_source(tmp_path: Path) -> None:
    a = analyse(project(tmp_path))
    assert a.split_line == 3
    assert format_source(a) == (
        "\\RequirePackage{fastinc-ini}\\documentclass{book}\n\\usepackage{tikz}\n\\endofdump\n"
    )


def test_run_main_keeps_line_numbers(tmp_path: Path) -> None:
    a = analyse(project(tmp_path))
    lines = split_lines(run_main(a, ["a"]))
    assert len(lines) == len(a.lines)
    assert lines[:2] == ["\n", "\n"]
    assert lines[2] == (
        "\\csname endofdump\\endcsname\\usepackage{fastinc}\\includeonly{a}\\tikzexternalize\n"
    )
    assert lines[3:] == list(a.lines[3:])
    assert "\\includeonly{}" in run_main(a, [])
    assert "includeonly" not in run_main(a, None)


def test_crlf_is_preserved(tmp_path: Path) -> None:
    a = analyse(project(tmp_path, "\r\n"))
    assert format_source(a).endswith("\\endofdump\r\n")
    assert all(line.endswith("\r\n") for line in split_lines(run_main(a, None)))


def test_full_mode_input(tmp_path: Path) -> None:
    a = analyse(project(tmp_path))
    assert full_mode_input(a) == "\\RequirePackage{fastinc-ini}\\input{doc.tex}"


def test_write_if_changed(tmp_path: Path) -> None:
    p = tmp_path / "d" / "x.tex"
    assert write_if_changed(p, "a\udcff")  # surrogate-escaped byte round-trips
    assert p.read_bytes() == b"a\xff"
    assert not write_if_changed(p, "a\udcff")
