"""Unit tests for proc, texdist, layout and shadow."""

import os
import sys
from pathlib import Path, PurePosixPath

import pytest

from chapmk import texdist
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
from chapmk.texdist import (
    TEX_DIR,
    MiKTeX,
    TeXLive,
    banner_line,
    detect,
    deterministic_env,
    tex_path,
)


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
    argv = tl.pdflatex("\\input{a.tex}", "thesis", tmp_path / "out", fmt=tmp_path / "pre.fmt")
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
    texlive = "pdfTeX 3.141592653-2.6-1.40.29 (TeX Live 2026)"
    miktex = "MiKTeX-pdfTeX 4.27 (MiKTeX 26.5)"
    with pytest.raises(ToolError, match="not found"):
        detect(which=lambda _: None)
    assert type(detect(lambda _: "/usr/bin/pdflatex", lambda _: texlive)) is TeXLive
    # by the path (Windows) or by the banner: on Linux MiKTeX's pdflatex is /usr/local/bin (S11)
    win = "C:/Program Files/MiKTeX/miktex/bin/x64/pdflatex.exe"
    assert isinstance(detect(lambda _: win, lambda _: miktex), MiKTeX)
    assert isinstance(detect(lambda _: "/usr/local/bin/pdflatex", lambda _: miktex), MiKTeX)


def test_banner_line_skips_warnings() -> None:
    """MiKTeX run as root warns on stderr before the banner (merged into the output); the
    banner decides the distribution and is part of the format fingerprint."""
    root = "pdflatex: security risk: running with elevated privileges\r\n"
    miktex = "MiKTeX-pdfTeX 4.27 (MiKTeX 26.5)\r\n© 2026 Han The Thanh\r\n"
    assert banner_line(root + miktex) == "MiKTeX-pdfTeX 4.27 (MiKTeX 26.5)"
    assert banner_line(miktex) == "MiKTeX-pdfTeX 4.27 (MiKTeX 26.5)"
    texlive = "pdfTeX 3.141592653-2.6-1.40.29 (TeX Live 2026)\nkpathsea version 6.4.1\n"
    assert banner_line(texlive) == "pdfTeX 3.141592653-2.6-1.40.29 (TeX Live 2026)"
    assert banner_line("\nsomething else\n") == "something else"
    assert banner_line("") == ""
    assert isinstance(
        detect(lambda _: "/usr/local/bin/pdflatex", lambda _: banner_line(root + miktex)), MiKTeX
    )


def test_miktex_command_lines(tmp_path: Path) -> None:
    """S11: format by --undump (TEXFORMATS is ignored), --max-print-line on every TeX call
    (the environment variable is ignored), SyncTeX paths without /./ and absolute queries."""
    mk = MiKTeX(which=lambda _: "/usr/local/bin/x", config_value=lambda _: "1")
    argv = mk.pdflatex("chapmk-run.tex", "thesis", tmp_path / "out", fmt=tmp_path / "f/pre.fmt")
    assert argv[:3] == [
        "pdflatex",
        f"--undump={(tmp_path / 'f/pre.fmt').as_posix()}",
        "--max-print-line=10000",
    ]
    assert {"-synctex=1", "-recorder", "-halt-on-error", "-jobname=thesis"} <= set(argv)
    assert argv[-1] == "chapmk-run.tex"
    assert not any(a.startswith(("-fmt", "--undump")) for a in mk.pdflatex("x", "j", tmp_path))
    fb = mk.format_build(tmp_path / "pre.tex", "pre", tmp_path)
    assert fb[:3] == ["pdflatex", "--max-print-line=10000", "-ini"]
    assert fb[-2:] == ["mylatexformat.ltx", tex_path(tmp_path / "pre.tex")]
    assert mk.biber("t", tmp_path) == TeXLive().biber("t", tmp_path)
    assert mk.environment(1, {}) == TeXLive().environment(1, {})
    src = Path("/doc")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(texdist, "_WINDOWS", False)
        assert mk.synctex_input(src, "main.tex") == "/doc/main.tex"
        assert mk.synctex_query(src, "ch/a.tex") == "/doc/ch/a.tex"
        # MiKTeX on Windows records native paths, backslashes also in the relative part
        mp.setattr(texdist, "_WINDOWS", True)
        assert mk.synctex_query(Path("C:/doc"), "ch/a.tex") == "C:\\doc\\ch\\a.tex"
    # the run main: relative to the shadow tree (MiKTeX would expand a TEXINPUTS name to an
    # absolute path, whose "_" breaks with the underscore package), bare name for TeX Live
    build = Path("/my_thesis/.chapmk/main")
    main = build / "runs" / "r1" / "chapmk-run.tex"
    assert mk.run_input(build / "src", main) == "../runs/r1/chapmk-run.tex"
    tl = TeXLive()
    assert tl.run_input(build / "src", main) == "chapmk-run.tex"
    assert tl.synctex_input(src, "main.tex") == f"{tex_path(src)}/./main.tex"
    assert tl.synctex_query(src, "ch/a.tex") == "ch/a.tex"


@pytest.mark.parametrize(("value", "ok"), [("0", True), ("1", True), ("2", False), ("", False)])
def test_miktex_on_the_fly_installation_must_not_prompt(value: str, ok: bool) -> None:
    """§6.16: 'ask' would prompt or block parallel runs; never (0) and always (1) are fine."""
    mk = MiKTeX(which=lambda _: "/bin/t", config_value=lambda _: value, find_file=lambda f: f)
    if ok:
        mk.check_tools()
    else:
        with pytest.raises(ToolError, match="AutoInstall"):
            mk.check_tools()
    with pytest.raises(ToolError, match="initexmf"):
        MiKTeX(
            which=lambda t: None if t == "initexmf" else "/bin/t", config_value=lambda _: "1"
        ).check_tools()


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
    shadow = src / ".chapmk" / "thesis" / "src"
    pairs = [(str(shadow), str(src)), (shadow.as_posix(), src.as_posix())]
    assert lay.path_map() == pairs[: 2 if os.sep == "\\" else 1]  # Windows: both forms
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


def test_missing_mylatexformat_is_reported_before_the_format_build() -> None:
    """Without mylatexformat the format build stops with only "! Emergency stop." in its log;
    check_tools names the package and how to install it (TeX Live, MiKTeX with on-the-fly
    installation "never"). With "always", MiKTeX installs it when the format build reads it."""
    found = lambda f: f  # noqa: E731
    absent = lambda f: "" if f == "mylatexformat.ltx" else f  # noqa: E731
    TeXLive(which=lambda _: "/bin/t", find_file=found).check_tools()
    with pytest.raises(ToolError, match=r"mylatexformat\.ltx.*tlmgr install mylatexformat"):
        TeXLive(which=lambda _: "/bin/t", find_file=absent).check_tools()
    never = MiKTeX(which=lambda _: "/bin/t", config_value=lambda _: "0", find_file=absent)
    with pytest.raises(ToolError, match="miktex packages install mylatexformat"):
        never.check_tools()
    MiKTeX(which=lambda _: "/bin/t", config_value=lambda _: "1", find_file=absent).check_tools()
