from pathlib import Path

import pytest

from fastinc.config import Config, load_config, parse_config_file
from fastinc.errors import ConfigError


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_defaults_without_file(tmp_path: Path) -> None:
    write(tmp_path / "doc.tex", "x")
    cfg = load_config(Path("doc.tex"), tmp_path)
    assert cfg.main == tmp_path / "doc.tex"
    assert cfg.build_dir is None and cfg.config_file is None
    assert cfg.effective_jobs >= 1


def test_file_values_and_cli_override(tmp_path: Path) -> None:
    write(tmp_path / "thesis.tex", "x")
    write(
        tmp_path / "fastinc.toml",
        'main = "thesis.tex"\njobs = 3\nbuild_dir = "b"\n'
        '[format]\nsplit_before = ["\\\\foo"]\n[units]\nheading = ["mychapter"]\n',
    )
    cfg = load_config(None, tmp_path)
    assert cfg.main == tmp_path / "thesis.tex"
    assert (cfg.jobs, cfg.build_dir) == (3, tmp_path / "b")
    assert cfg.split_before == (r"\foo",)
    assert cfg.unit_headings == ("mychapter",)
    cfg2 = load_config(None, tmp_path, jobs=8, out_dir=Path("o"))
    assert (cfg2.jobs, cfg2.out_dir) == (8, tmp_path / "o")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("jobs = -1", "non-negative"),
        ("unknown = 1", "unknown setting"),
        ('[format]\nsplit_before = ["("]', "invalid regular expression"),
        ('[lint]\nallow = "x"', "list of strings"),
        ("main = [", "Invalid|Expected|expected"),
    ],
)
def test_invalid_files(tmp_path: Path, text: str, message: str) -> None:
    f = write(tmp_path / "fastinc.toml", text)
    with pytest.raises(ConfigError, match=message):
        parse_config_file(f)


def test_missing_main(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no main file"):
        load_config(None, tmp_path)
    with pytest.raises(ConfigError, match="not found"):
        load_config(Path("nope.tex"), tmp_path)
    write(tmp_path / "x.ltx", "")
    with pytest.raises(ConfigError, match=r"\.tex"):
        load_config(Path("x.ltx"), tmp_path)


def test_effective_jobs() -> None:
    assert Config(jobs=5).effective_jobs == 5
