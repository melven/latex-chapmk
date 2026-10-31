from pathlib import Path

import pytest

from fastinc.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "fastinc 0.1.0" in capsys.readouterr().out


def test_config_errors_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["build"], cwd=tmp_path) == 2
    assert "no main file" in capsys.readouterr().err
    (tmp_path / "d.tex").write_text("\\begin{document}\\include{../x}\\end{document}")
    assert main(["build", "d.tex"], cwd=tmp_path) == 2
    assert "absolute paths and '..'" in capsys.readouterr().err
