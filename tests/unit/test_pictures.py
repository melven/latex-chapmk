"""Picture cache helpers (design §6.17): records, driver file, garbage collection."""

from pathlib import Path

import pytest

from chapmk.config import ConfigError, parse_config_file
from chapmk.deps import short_hash
from chapmk.pictures import (
    INPUTS_FILE,
    PictureRecord,
    check_inputs,
    collect_garbage,
    driver_file,
    picture_stamp,
    read_pictures,
    record_inputs,
    remove_figures,
    stale_figures,
    store_references,
)
from chapmk.recorder import stat_signatures

KEY_A = "0B1360971630C73019099E9F886EC9A7"
KEY_B = "40DEAF2B0E91DA6C2B120A60FC4ECAE6"


def test_read_pictures(tmp_path: Path) -> None:
    log = tmp_path / "main.log"
    long = "\\draw " + "(0,0) -- " * 2000  # longer than max_print_line: broken by TeX
    first = f"chapmk-picture: s {KEY_A} " + long
    log.write_text(
        "(./chapter.tex\n" + first[:10000] + "\n" + first[10000:] + "\n"
        f"chapmk-picture: x {KEY_A} 7 6.63135pt U2\n"
        "Overfull \\hbox\n"
        f"chapmk-picture: u {KEY_B} G1\n"
        "chapmk-picture: x tooshort 1 0.0pt U1\n"
    )
    assert read_pictures(log) == [
        PictureRecord(KEY_A, "U2", True, 7, "6.63135pt", long),
        PictureRecord(KEY_B, "G1", False),
    ]
    assert read_pictures(tmp_path / "missing.log") == []


def test_driver_file(tmp_path: Path) -> None:
    shadow = tmp_path / "b" / "src"
    text = driver_file(tmp_path / "b" / "fig", shadow, "S", {"U1": "d1", "G0": "g"})
    assert text == (
        "\\expandafter\\def\\csname chapmk@picdir\\endcsname{../fig/}%\n"
        "\\expandafter\\def\\csname chapmk@picstamp\\endcsname{S}%\n"
        "\\expandafter\\def\\csname chapmk@picrefs@G0\\endcsname{g}%\n"
        "\\expandafter\\def\\csname chapmk@picrefs@U1\\endcsname{d1}%\n"
    )
    # no cache: empty directory, pictures are typeset inline
    assert driver_file(None, shadow, "S", {}).startswith(
        "\\expandafter\\def\\csname chapmk@picdir\\endcsname{}%"
    )


def test_collect_garbage(tmp_path: Path) -> None:
    for key in (KEY_A, KEY_B):
        (tmp_path / f"{key}.pdf").write_text("x")
        (tmp_path / f"{key}.dpth").write_text("0pt")
    collect_garbage(tmp_path, {KEY_A})
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{KEY_A}.dpth", f"{KEY_A}.pdf"]
    collect_garbage(tmp_path / "missing", set())


def test_stale_figures(tmp_path: Path) -> None:
    """A figure is stale when a key its code references changes value, becomes defined or
    becomes undefined; other keys do not matter."""
    rec = PictureRecord(KEY_A, "U1", True, 0, "0pt", "\\node {see \\ref{fig:a} and \\cite{k}};")
    values = {"L:fig:a": "1", "L:other": "2"}
    store_references(tmp_path, rec, values, tmp_path)
    assert stale_figures(tmp_path, values) == []
    assert stale_figures(tmp_path, {**values, "L:other": "3"}) == []
    assert stale_figures(tmp_path, {**values, "L:fig:a": "9"}) == [KEY_A]
    assert stale_figures(tmp_path, {**values, "C:k": "1"}) == [KEY_A]  # newly defined
    assert stale_figures(tmp_path, {"L:other": "2"}) == [KEY_A]  # undefined now
    (tmp_path / f"{KEY_A}.pdf").write_text("x")
    remove_figures(tmp_path, [KEY_A])
    assert list(tmp_path.iterdir()) == []


def test_config_picture_cache(tmp_path: Path) -> None:
    cfg = tmp_path / "chapmk.toml"
    cfg.write_text("[pictures]\ncache = false\n")
    assert parse_config_file(cfg).picture_cache is False
    cfg.write_text("[pictures]\ncache = 1\n")
    with pytest.raises(ConfigError, match="true or false"):
        parse_config_file(cfg)


def test_stale_figures_files(tmp_path: Path) -> None:
    """A figure is stale when a file it read (recorded) or names in its code (a table) changes
    or disappears."""
    src, fig = tmp_path / "src", tmp_path / "fig"
    (src / "data").mkdir(parents=True)
    fig.mkdir()
    (src / "data" / "t.dat").write_text("1 2\n")
    (src / "inc.tex").write_text("x")
    code = "\\begin{axis}\\addplot table {data/t.dat};\\end{axis}"
    store_references(fig, PictureRecord(KEY_A, "U1", True, 0, "0pt", code, ("./inc.tex",)), {}, src)
    assert stale_figures(fig, None, src) == []
    (src / "data" / "t.dat").write_text("1 3\n")
    assert stale_figures(fig, None, src) == [KEY_A]
    store_references(fig, PictureRecord(KEY_A, "U1", True, 0, "0pt", code, ("./inc.tex",)), {}, src)
    (src / "inc.tex").unlink()
    assert stale_figures(fig, None, src) == [KEY_A]


def test_cache_inputs(tmp_path: Path) -> None:
    """C4: the cache records the distribution files of exporting runs; garbage collection
    keeps the record; a changed file empties the cache."""
    fig, pkg = tmp_path / "fig", tmp_path / "pgf.sty"
    pkg.write_text("v1")
    record_inputs(fig, stat_signatures([pkg]))
    (fig / f"{KEY_A}.pdf").write_text("x")
    collect_garbage(fig, {KEY_A})
    assert sorted(p.name for p in fig.iterdir()) == [f"{KEY_A}.pdf", INPUTS_FILE]
    assert check_inputs(fig) is False
    pkg.write_text("v22")
    assert check_inputs(fig) is True
    assert list(fig.iterdir()) == []
    assert check_inputs(fig) is False


def test_picture_stamp() -> None:
    """The stamp is part of every figure key: a change of its text invalidates all caches."""
    fingerprints = {"preamble": "p", "main": "m"}
    assert picture_stamp("fmt", fingerprints) == short_hash('fmt{"main": "m", "preamble": "p"}')
