"""Unit tests for proc, texdist, layout and shadow."""

import os
import sys
from pathlib import Path, PurePosixPath

import pytest

from chapmk.analysis import analyse
from chapmk.config import Config
from chapmk.errors import ToolError
from chapmk.layout import make_layout
from chapmk.proc import run
from chapmk.shadow import (
    build_output_filter,
    changed_signatures,
    external_inputs,
    stat_signatures,
    sync_project_shadow,
    sync_shadow,
)
from chapmk.texdist import TEX_DIR, TeXLive, detect, deterministic_env, tex_path


def test_run_captures_output_and_errors(tmp_path: Path) -> None:
    r = run(
        [sys.executable, "-c", "import sys; print('hi'); sys.exit(3)"],
        cwd=tmp_path,
        env=dict(os.environ),
        log_path=tmp_path / "x.log",
    )
    assert (r.returncode, r.output.strip(), r.ok) == (3, "hi", False)
    assert (tmp_path / "x.log").read_text().strip() == "hi"
    with pytest.raises(ToolError, match="not found"):
        run(["no-such-program-xyz"], cwd=tmp_path, env={})
    with pytest.raises(ToolError, match="timed out"):
        run(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout=0.2,
        )


def test_texlive_command_lines(tmp_path: Path) -> None:
    tl = TeXLive(which=lambda _: "/usr/bin/x")
    argv = tl.pdflatex("\\input{a.tex}", "thesis", tmp_path / "out", fmt="pre")
    assert argv[:2] == ["pdflatex", "-fmt=pre"]
    assert f"-output-directory={(tmp_path / 'out').as_posix()}" in argv
    assert {"-synctex=1", "-recorder", "-halt-on-error", "-jobname=thesis"} <= set(argv)
    assert argv[-1] == "\\input{a.tex}"
    assert "-fmt" not in " ".join(tl.pdflatex("x", "j", tmp_path))
    fb = tl.format_build(tmp_path / "pre.tex", "pre", tmp_path)
    assert fb[:2] == ["pdflatex", "-ini"] and fb[-3:] == [
        "&pdflatex",
        "mylatexformat.ltx",
        tex_path(tmp_path / "pre.tex"),
    ]
    assert tl.biber("thesis", tmp_path) == ["biber", "--output-directory", str(tmp_path), "thesis"]
    assert tl.makeindex("t.nlo", "t.nls", "nomencl.ist") == [
        "makeindex",
        "-s",
        "nomencl.ist",
        "-o",
        "t.nls",
        "t.nlo",
    ]
    assert tl.makeindex("t.idx", "t.ind", None) == ["makeindex", "-o", "t.ind", "t.idx"]


def test_texlive_environment(tmp_path: Path) -> None:
    env = TeXLive().environment(1700000000, {"PATH": "/bin", "TEXINPUTS": "/x"}, tmp_path)
    assert env["PATH"] == "/bin"
    assert env["SOURCE_DATE_EPOCH"] == "1700000000" and env["FORCE_SOURCE_DATE"] == "1"
    assert env["TEXINPUTS"] == f"{TEX_DIR}{os.pathsep}/x"
    assert env["TEXFORMATS"] == f"{tmp_path}{os.pathsep}"
    assert "TEXFORMATS" not in TeXLive().environment(1, {})
    assert deterministic_env(5)["max_print_line"] == "10000"


def test_check_tools_and_detect() -> None:
    with pytest.raises(ToolError, match="biber, makeindex"):
        TeXLive(which=lambda t: None if t in ("biber", "makeindex") else "/bin/t").check_tools()
    with pytest.raises(ToolError, match="MiKTeX"):
        detect(which=lambda _: "C:/Program Files/MiKTeX/bin/pdflatex.exe")
    with pytest.raises(ToolError, match="not found"):
        detect(which=lambda _: None)
    assert isinstance(detect(which=lambda _: "/usr/bin/pdflatex"), TeXLive)


def project(tmp_path: Path) -> Config:
    src = tmp_path / "src"
    (src / "ch").mkdir(parents=True)
    (src / "fig").mkdir()
    (src / ".git").mkdir()
    (src / ".git" / "HEAD").write_text("x")
    (src / "ch" / "a.tex").write_text("\\chapter{A}")
    (src / "ch" / "a.aux").write_text("stale")
    (src / "fig" / "x.pdf").write_text("pdf")
    for name in ("thesis.aux", "thesis.toc", "thesis.pdf", "thesis-notes.tex", "other.aux"):
        (src / name).write_text("x")
    (src / "thesis.tex").write_text(
        "\\documentclass{book}\\begin{document}\\include{ch/a}\\end{document}"
    )
    return Config(main=src / "thesis.tex")


def files_in(d: Path) -> set[str]:
    return {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() or p.is_symlink()}


def test_layout_defaults_and_overrides(tmp_path: Path) -> None:
    cfg = project(tmp_path)
    a = analyse(cfg)
    lay = make_layout(cfg, a)
    src = tmp_path / "src"
    assert (lay.build_dir, lay.out_dir, lay.jobname) == (src / ".chapmk" / "thesis", src, "thesis")
    assert lay.shadow_dir == src / ".chapmk" / "thesis" / "src"
    assert lay.output(".pdf") == src / "thesis.pdf"
    assert lay.path_map() == [(str(src / ".chapmk" / "thesis" / "src"), str(src))]
    lay2 = make_layout(Config(main=cfg.main, build_dir=tmp_path / "b", out_dir=tmp_path / "o"), a)
    assert (lay2.build_dir, lay2.out_dir) == (tmp_path / "b", tmp_path / "o")


def test_build_output_filter(tmp_path: Path) -> None:
    excluded = build_output_filter(analyse(project(tmp_path)))
    assert excluded(PurePosixPath("thesis.aux")) and excluded(PurePosixPath("ch/a.aux"))
    assert not excluded(PurePosixPath("thesis.tex"))
    assert not excluded(PurePosixPath("thesis-notes.tex"))
    assert not excluded(PurePosixPath("thesis.cfg"))  # a source named like the job
    assert excluded(PurePosixPath("thesis.synctex.gz")) and excluded(
        PurePosixPath("thesis.run.xml")
    )
    assert not excluded(PurePosixPath("sub/thesis.aux"))


def test_shadow_tree_sync_and_refresh(tmp_path: Path) -> None:
    cfg = project(tmp_path)
    a = analyse(cfg)
    src, shadow, build = (
        tmp_path / "src",
        tmp_path / "src" / ".chapmk" / "thesis" / "src",
        tmp_path / "src" / ".chapmk" / "thesis",
    )
    other = tmp_path / "src" / ".chapmk" / "other"  # another job's build directory
    other.mkdir(parents=True)
    (other / "x.tex").write_text("x")
    stats = sync_project_shadow(a, shadow, build)
    assert files_in(shadow) == {
        "thesis.tex",
        "thesis-notes.tex",
        "other.aux",
        "ch/a.tex",
        "fig/x.pdf",
    }
    assert stats.created == stats.total == 5
    assert (shadow / "ch" / "a.tex").is_symlink() and (
        shadow / "ch" / "a.tex"
    ).read_text() == "\\chapter{A}"
    # idempotent
    assert sync_project_shadow(a, shadow, build).created == 0
    # refresh: removed and added files, stray files in the shadow tree
    (src / "fig" / "x.pdf").unlink()
    (src / "fig" / "y.pdf").write_text("y")
    (shadow / "stray.aux").write_text("x")
    stats = sync_project_shadow(a, shadow, build)
    assert files_in(shadow) == {
        "thesis.tex",
        "thesis-notes.tex",
        "other.aux",
        "ch/a.tex",
        "fig/y.pdf",
    }
    assert (stats.created, stats.removed) == (1, 2)


def test_shadow_skips_given_dirs(tmp_path: Path) -> None:
    (tmp_path / "s" / "out").mkdir(parents=True)
    (tmp_path / "s" / "out" / "f").write_text("x")
    (tmp_path / "s" / "a").write_text("x")
    sync_shadow(
        tmp_path / "s",
        tmp_path / "sh",
        skip_dirs=[tmp_path / "s" / "out"],
        excluded=lambda _: False,
    )
    assert files_in(tmp_path / "sh") == {"a"}


def test_external_inputs_and_signatures(tmp_path: Path) -> None:
    """C4: files read outside the shadow tree, build and source directory (the distribution)
    are found by their .fls lines; a size or mtime change or a removal is detected."""
    src, build, dist = tmp_path / "src", tmp_path / "build", tmp_path / "texmf"
    shadow = build / "src"
    for d in (src, shadow, dist):
        d.mkdir(parents=True)
    (src / "a.tex").write_text("x")
    (shadow / "a.tex").symlink_to(src / "a.tex")
    (dist / "p.sty").write_text("p")
    (dist / "q.sty").write_text("q")
    (build / "main.aux").write_text("")
    fls = tmp_path / "main.fls"
    fls.write_text(
        f"PWD {shadow}\nINPUT ./a.tex\nINPUT {dist}/p.sty\nINPUT {dist}/../texmf/q.sty\n"
        f"INPUT {build}/main.aux\nINPUT {dist}/missing.sty\nOUTPUT {dist}/out.tex\n"
    )
    found = external_inputs(fls, shadow, (shadow, build, src))
    assert found == {dist / "p.sty", dist / "q.sty"}
    sigs = stat_signatures(found)
    assert changed_signatures(sigs) == []
    (dist / "p.sty").write_text("pp")
    (dist / "q.sty").unlink()
    assert sorted(changed_signatures(sigs)) == [(dist / n).as_posix() for n in ("p.sty", "q.sty")]
