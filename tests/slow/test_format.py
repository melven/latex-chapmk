"""Format build against real TeX (S1 as a regression test)."""

import os
from pathlib import Path

import pytest
from conftest import EPOCH

from chapmk.analysis import analyse
from chapmk.config import Config
from chapmk.errors import TexError
from chapmk.files import write_if_changed
from chapmk.fmt import ensure_format
from chapmk.gensrc import run_main
from chapmk.layout import make_layout
from chapmk.proc import run
from chapmk.shadow import sync_project_shadow
from chapmk.texdist import detect

pytestmark = pytest.mark.slow


def test_format_build_reuse_and_run(copy_corpus) -> None:  # type: ignore[no-untyped-def]
    src = copy_corpus("minimal/S1-format")
    cfg = Config(main=src / "main.tex")
    a = analyse(cfg)
    assert a.split_line == 193  # \ifdraft{ block (S1)
    lay = make_layout(cfg, a)
    sync_project_shadow(a, lay.shadow_dir, lay.build_dir)
    dist = detect()
    env = dist.environment(int(EPOCH), os.environ, lay.fmt_dir)
    info = ensure_format(a, lay, dist, env)
    assert info.rebuilt and (lay.fmt_dir / "pre.fmt").is_file()
    assert not ensure_format(a, lay, dist, env).rebuilt
    # a run with the format and the generated run main succeeds
    out = lay.build_dir / "run"
    out.mkdir()
    write_if_changed(out / "main.tex", run_main(a, None).replace("\\usepackage{chapmk}", ""))
    r = run(
        dist.pdflatex(str(out / "main.tex"), "main", out, fmt=info.path),
        cwd=lay.shadow_dir,
        env=env,
    )
    assert r.ok, r.output[-2000:]
    assert "start reading document" in (out / "main.log").read_text()


@pytest.mark.parametrize(
    ("line2", "expected"),
    [
        ("\\usepackage{nonexistent-pkg}", "nonexistent-pkg"),
        # a file:line error names the main file: pre.tex keeps its line numbers
        ("\\undefinedmacro", "d.tex:2: Undefined control sequence"),
    ],
)
def test_format_build_error_is_mapped(tmp_path: Path, line2: str, expected: str) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "d.tex").write_text(
        f"\\documentclass{{article}}\n{line2}\n"
        "\\tikzexternalize\n\\begin{document}x\\end{document}\n"
    )
    cfg = Config(main=src / "d.tex")
    a = analyse(cfg)
    lay = make_layout(cfg, a)
    sync_project_shadow(a, lay.shadow_dir, lay.build_dir)
    dist = detect()
    with pytest.raises(TexError) as err:
        ensure_format(a, lay, dist, dist.environment(1, os.environ, lay.fmt_dir))
    message = err.value.first_error or ""
    assert expected in message and "pre.tex" not in message, message


def test_pdf_objects_in_the_format_fall_back(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """Code that creates PDF form xobjects cannot be dumped (pgf manual: fadings); the build
    falls back to full mode with a reason instead of failing in TeX."""
    from chapmk.cli import main

    src = tmp_path / "s"
    src.mkdir()
    (src / "d.tex").write_text(
        "\\documentclass{article}\n\\setbox0\\hbox{x}\\immediate\\pdfxform0\n\\usepackage{bookmark}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    # \pdfobj is on the deny list: split before it, the format holds no object
    assert main(["build", "d.tex", "-v"], cwd=src) == 0
    assert "format build failed" not in capsys.readouterr().err
    # hidden from the deny list (\csname): caught by the format check
    (src / "e.tex").write_text(
        "\\documentclass{article}\n\\setbox0\\hbox{x}\\immediate\\csname pdfxform\\endcsname0\n"
        "\\usepackage{bookmark}\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert main(["build", "e.tex", "-v"], cwd=src) == 0
    err = capsys.readouterr().err
    assert "full build: format build failed" in err and "creates PDF form xobjects" in err
