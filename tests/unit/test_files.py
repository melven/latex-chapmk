"""Unit tests for files.py and logs.run_error: digests, decoding, first error of a run."""

from pathlib import Path

from chapmk.files import (
    changed_files,
    digest,
    read_log,
    read_raw,
    recorded_name,
    source_name,
    write_atomic,
)
from chapmk.logs import run_error
from chapmk.shadow import source_inputs


def test_changed_files(tmp_path: Path) -> None:
    (tmp_path / "a.tex").write_text("a")
    (tmp_path / "b.tex").write_text("b")
    digests = {"a.tex": digest(tmp_path / "a.tex"), "b.tex": "old", "gone.tex": "x"}
    assert changed_files(tmp_path, digests) == ["b.tex", "gone.tex"]


def test_read_raw_and_read_log_decode_utf8_not_the_locale(tmp_path: Path) -> None:
    data = "Grüße\r\n".encode() + b"\xff\n"
    path = tmp_path / "x.log"
    path.write_bytes(data)
    raw = read_raw(path)
    assert raw.startswith("Grüße\r\n")  # no newline translation
    write_atomic(tmp_path / "y", raw)
    assert (tmp_path / "y").read_bytes() == data  # byte round trip
    assert read_log(path) == "Grüße\r\n�\n"


def test_run_error_from_log_or_output(tmp_path: Path) -> None:
    log = tmp_path / "main.log"
    mapping = [("/shadow", "/src")]
    assert run_error(log, "! Emergency stop.\n", mapping) == "! Emergency stop."
    log.write_text("x\n/shadow/ch1.tex:3: Undefined control sequence.\n")
    assert run_error(log, "", mapping) == "/src/ch1.tex:3: Undefined control sequence."


def test_source_inputs(tmp_path: Path) -> None:
    src, shadow = tmp_path / "src", tmp_path / "shadow"
    (src / "ch").mkdir(parents=True)
    (shadow / "ch").mkdir(parents=True)
    for name in ("main.tex", "ch/a.tex"):
        (src / name).write_text("x")
        (shadow / name).symlink_to(src / name)
    (shadow / "generated.tex").write_text("only in the shadow tree")
    fls = tmp_path / "run.fls"
    fls.write_text(
        f"PWD {shadow}\nINPUT ./main.tex\nINPUT {shadow}/ch/a.tex\nINPUT generated.tex\n"
        "INPUT /usr/share/texmf/tex/latex/base/book.cls\n"
    )
    assert source_inputs(fls, shadow, src) == {"main.tex", "ch/a.tex"}


def test_recorded_and_source_names(tmp_path: Path) -> None:
    (tmp_path / "ch").mkdir()
    (tmp_path / "ch" / "a.tex").write_text("a")
    for recorded in ("/ch/a.tex", "./ch/a.tex", "ch/a.tex", "//./ch/a.tex"):
        assert recorded_name(recorded) == "ch/a.tex"
        assert source_name(recorded, tmp_path) == "ch/a.tex"
    assert source_name("ch/b.tex", tmp_path) is None
    assert source_name("ch", tmp_path) is None  # a directory
    assert source_name("/", tmp_path) is None
