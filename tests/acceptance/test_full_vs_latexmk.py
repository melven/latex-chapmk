"""M1 acceptance: ``fastinc build --full`` equals plain latexmk (PLAN §3.3, §9 M1).

Both builds use the same environment (N4) and inject fastinc-ini before \\documentclass
(externalize neutralisation, §6.4.3); latexmk gets a rule for nomencl.
"""

import os
from pathlib import Path

import pytest

from fastinc.analysis import analyse
from fastinc.check import compare_pdfs, compare_synctex
from fastinc.cli import main
from fastinc.config import Config
from fastinc.proc import run
from fastinc.texdist import TeXLive

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]

EPOCH = 1700000000
LATEXMKRC = r"""
add_cus_dep('nlo', 'nls', 0, 'nlo2nls');
sub nlo2nls {
  my ($dir, $base) = ($_[0] =~ m{^(.*)/([^/]+)$}) ? ($1, $2) : ('.', $_[0]);
  return system("cd '$dir' && makeindex -s nomencl.ist -o '$base.nls' '$base.nlo'");
}
"""


def latexmk(src: Path, main_name: str, outdir: Path) -> None:
    rc = outdir.parent / "latexmkrc"
    rc.write_text(LATEXMKRC)
    argv = [
        "latexmk",
        "-pdf",
        "-synctex=1",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-outdir={outdir}",
        "-r",
        str(rc),
        "-usepretex=\\RequirePackage{fastinc-ini}",
        f"-jobname={Path(main_name).stem}",
        main_name,
    ]
    env = TeXLive().environment(EPOCH, os.environ)
    r = run(argv, cwd=src, env=env)
    assert r.ok, r.output[-3000:]


@pytest.mark.parametrize(
    ("corpus", "variant"),
    [("thesis", "twoside"), ("thesis", "oneside"), ("hgb", None)],
)
def test_full_build_matches_latexmk(
    copy_corpus,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    corpus: str,
    variant: str | None,
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    src = copy_corpus(corpus)
    main_tex = src / "main.tex"
    if variant == "oneside":
        lines = main_tex.read_text().split("\n")
        lines[0] = lines[0].replace("twoside", "oneside")
        main_tex.write_text("\n".join(lines))
    assert main(["build", "main.tex", "--full", "--out-dir", str(tmp_path / "fi")], cwd=src) == 0
    latexmk(src, "main.tex", tmp_path / "lmk")

    ours, ref = tmp_path / "fi" / "main.pdf", tmp_path / "lmk" / "main.pdf"
    report = compare_pdfs(ref, ours)
    sources = ["main.tex"] + [f"{inc.arg}.tex" for inc in analyse(Config(main=main_tex)).includes]
    compare_synctex(ref, ours, sources, src, report=report)
    print(report.summary())
    assert report.ok, report.summary()
    assert report.counts["synctex view"] >= 5 * len(sources) // 2
