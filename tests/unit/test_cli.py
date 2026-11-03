from pathlib import Path

import pytest

import chapmk
from chapmk.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert f"chapmk {chapmk.__version__}" in capsys.readouterr().out


def test_config_errors_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["build"], cwd=tmp_path) == 2
    assert "no main file" in capsys.readouterr().err
    (tmp_path / "d.tex").write_text("\\begin{document}\\include{../x}\\end{document}")
    assert main(["build", "d.tex"], cwd=tmp_path) == 2
    assert "absolute paths and '..'" in capsys.readouterr().err


def test_build_lock(tmp_path: Path) -> None:
    """C6: one process per build directory; a second one waits (with a message) or fails."""
    import threading
    import time

    from chapmk.lock import LockedError, build_lock

    messages: list[str] = []
    with build_lock(tmp_path / "b"):
        busy = r"in use by another chapmk process \(pid \d+\)"
        with pytest.raises(LockedError, match=busy), build_lock(tmp_path / "b", wait=False):
            pass
        got = threading.Event()

        def second() -> None:
            with build_lock(tmp_path / "b", say=messages.append):
                got.set()

        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.5)
        assert not got.is_set() and messages and "waiting" in messages[0]
    t.join(5)
    assert got.is_set()


def test_locked_build_dir_no_wait(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``build --no-wait`` and ``clean --no-wait`` fail with exit 2 while another process holds
    the lock; ``clean`` removes the build directory with its lock file afterwards."""
    from chapmk.lock import build_lock

    (tmp_path / "d.tex").write_text("\\documentclass{book}\\begin{document}x\\end{document}\n")
    build = tmp_path / ".chapmk" / "d"
    assert main(["clean", "d.tex"], cwd=tmp_path) == 0
    build.mkdir(parents=True)
    (build / ".chapmk-build-dir").touch()
    with build_lock(build):
        assert main(["build", "d.tex", "--no-wait"], cwd=tmp_path) == 2
        assert "in use by another chapmk process" in capsys.readouterr().err
        assert main(["clean", "d.tex", "--no-wait"], cwd=tmp_path) == 2
    assert main(["clean", "d.tex"], cwd=tmp_path) == 0
    assert not (tmp_path / ".chapmk").exists()


def test_internal_error_exit_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """C9: an unexpected exception is an internal error: exit 3, one line, the traceback only
    with -v."""
    import chapmk.cli

    def boom(*_args: object) -> int:
        raise KeyError("x")

    monkeypatch.setattr(chapmk.cli, "cmd_build", boom)
    assert main(["build", "d.tex"], cwd=tmp_path) == 3
    err = capsys.readouterr().err
    assert "internal error: KeyError" in err and "Traceback" not in err and "-v" in err
    assert main(["build", "d.tex", "-v"], cwd=tmp_path) == 3
    assert "Traceback" in capsys.readouterr().err


def test_check_tools_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """R2: check names its missing programs before any build."""
    import shutil

    from chapmk.check import check_tools
    from chapmk.errors import ToolError

    real = shutil.which
    monkeypatch.setattr(shutil, "which", lambda t: None if t == "pdftoppm" else real(t))
    with pytest.raises(ToolError, match="pdftoppm"):
        check_tools()
