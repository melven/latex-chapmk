from pathlib import Path

import pytest

from chapmk.analysis import analyse
from chapmk.config import Config
from chapmk.files import write_if_changed
from chapmk.gensrc import format_source, full_mode_input, run_main
from chapmk.texsource import split_lines


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
    src = format_source(a)
    lines = split_lines(src)
    assert len(lines) == a.split_line  # lines 1..s-1 (numbers kept), then the probes
    assert lines[0] == (
        "\\expandafter\\def\\csname chapmk@formatbuild\\endcsname{}"
        "\\RequirePackage{chapmk-ini}\\documentclass{book}\n"
    )
    assert lines[1] == "\\usepackage{tikz}\n"
    # probes of the state a format cannot keep (S13), then the end of the dump
    for probe in ("chapmk-pdf-objects:", "chapmk-pdf-colorstacks:", "chapmk-pdf-unrecorded:"):
        assert probe in lines[-1]
    assert src.endswith("\\endofdump\n")


def test_run_main_keeps_line_numbers(tmp_path: Path) -> None:
    a = analyse(project(tmp_path))
    lines = split_lines(run_main(a, ["a"]))
    assert len(lines) == len(a.lines)
    assert lines[0] == "\n"
    assert lines[1] == "\\csname endofdump\\endcsname\\usepackage{chapmk}\\includeonly{a}\n"
    assert lines[2:] == list(a.lines[2:])  # the split statement starts on a fresh line
    assert "\\includeonly{}" in run_main(a, [])
    assert "includeonly" not in run_main(a, None)
    deny = split_lines(run_main(a, None, ["foo@cnt", "bar"]))[1]
    assert deny.startswith(
        "\\csname endofdump\\endcsname\\expandafter\\def\\csname chapmk@denynames\\endcsname"
        "{foo@cnt,bar}\\usepackage{chapmk}"
    )


def test_crlf_is_preserved(tmp_path: Path) -> None:
    a = analyse(project(tmp_path, "\r\n"))
    assert format_source(a).endswith("\\endofdump\r\n")
    assert all(line.endswith("\r\n") for line in split_lines(run_main(a, None)))


def test_full_mode_input(tmp_path: Path) -> None:
    a = analyse(project(tmp_path))
    assert full_mode_input(a) == "\\RequirePackage{chapmk-ini}\\input{doc.tex}"


def test_write_if_changed(tmp_path: Path) -> None:
    p = tmp_path / "d" / "x.tex"
    assert write_if_changed(p, "a\udcff")  # surrogate-escaped byte round-trips
    assert p.read_bytes() == b"a\xff"
    assert not write_if_changed(p, "a\udcff")


def test_write_atomic_keeps_old_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C7: a write that fails midway (disk full, kill) leaves the old file, no temp file."""
    from chapmk.files import write_atomic

    p = tmp_path / "canon" / "a.aux"
    write_atomic(p, "old\n")
    real = Path.write_bytes

    def partial(self: Path, data: bytes) -> int:
        real(self, data[:2])
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", partial)
    with pytest.raises(OSError):
        write_atomic(p, "new content\n")
    monkeypatch.undo()
    assert p.read_text() == "old\n" and [f.name for f in p.parent.iterdir()] == ["a.aux"]
