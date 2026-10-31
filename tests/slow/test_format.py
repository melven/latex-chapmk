"""Format build against real TeX (S1 as a regression test)."""

import os
from pathlib import Path

import pytest

from fastinc.analysis import analyse
from fastinc.config import Config
from fastinc.errors import TexError
from fastinc.fmt import ensure_format
from fastinc.gensrc import run_main, write_if_changed
from fastinc.layout import make_layout
from fastinc.proc import run
from fastinc.shadow import sync_project_shadow
from fastinc.texdist import detect

pytestmark = pytest.mark.slow


def test_format_build_reuse_and_run(copy_corpus) -> None:  # type: ignore[no-untyped-def]
    src = copy_corpus("minimal/S1-format")
    cfg = Config(main=src / "main.tex")
    a = analyse(cfg)
    assert a.split_line == 193  # \ifdraft{ block (S1)
    lay = make_layout(cfg, a)
    sync_project_shadow(a, lay.shadow_dir, lay.build_dir)
    dist = detect()
    env = dist.environment(1700000000, os.environ, lay.fmt_dir)
    info = ensure_format(a, lay, dist, env)
    assert info.rebuilt and (lay.fmt_dir / "pre.fmt").is_file()
    assert not ensure_format(a, lay, dist, env).rebuilt
    # a run with the format and the generated run main succeeds
    out = lay.build_dir / "run"
    out.mkdir()
    write_if_changed(out / "main.tex", run_main(a, None).replace("\\usepackage{fastinc}", ""))
    r = run(
        dist.pdflatex(str(out / "main.tex"), "main", out, fmt=info.name),
        cwd=lay.shadow_dir,
        env=env,
    )
    assert r.ok, r.output[-2000:]
    assert "start reading document" in (out / "main.log").read_text()


def test_format_build_error_is_mapped(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "d.tex").write_text(
        "\\documentclass{article}\n\\usepackage{nonexistent-pkg}\n"
        "\\tikzexternalize\n\\begin{document}x\\end{document}\n"
    )
    cfg = Config(main=src / "d.tex")
    a = analyse(cfg)
    lay = make_layout(cfg, a)
    sync_project_shadow(a, lay.shadow_dir, lay.build_dir)
    dist = detect()
    with pytest.raises(TexError) as err:
        ensure_format(a, lay, dist, dist.environment(1, os.environ, lay.fmt_dir))
    assert "nonexistent-pkg" in (err.value.first_error or "")
