"""M1/M7 acceptance: ``chapmk build --full`` equals plain latexmk (PLAN §3.3, §9 M1).

Both builds use the same environment (N4); latexmk gets a rule for nomencl. latexmk runs the
unmodified document with shell escape, so the user's TikZ externalize (thesis corpus, draft
mode) makes its figures with its own figure jobs; chapmk redirects externalize to its picture
cache (§6.4.3, §6.17) and must give the same result. latexmk builds in the source directory:
externalize's figure jobs read the main aux from there.
"""

import os
from pathlib import Path

import pytest
from conftest import reuse_reference, source_hash

from chapmk.analysis import analyse
from chapmk.check import compare_pdfs, compare_synctex
from chapmk.cli import main
from chapmk.config import Config
from chapmk.proc import run
from chapmk.texdist import TeXLive

pytestmark = [pytest.mark.slow, pytest.mark.acceptance]

EPOCH = 1700000000
LATEXMKRC = r"""
add_cus_dep('nlo', 'nls', 0, 'nlo2nls');
sub nlo2nls {
  my ($dir, $base) = ($_[0] =~ m{^(.*)/([^/]+)$}) ? ($1, $2) : ('.', $_[0]);
  return system("cd '$dir' && makeindex -s nomencl.ist -o '$base.nls' '$base.nlo'");
}
"""


def latexmk(src: Path, main_name: str, rc_dir: Path) -> Path:
    """latexmk with shell escape in ``src`` (reused from the reference cache, conftest);
    returns the PDF."""
    job = Path(main_name).stem
    key = source_hash(src, "latexmk", main_name, LATEXMKRC, str(EPOCH))
    outputs = {f"ref{s}": src / f"{job}{s}" for s in (".pdf", ".synctex.gz")}
    reuse_reference(key, src, outputs, lambda: _latexmk(src, main_name, rc_dir))
    return src / f"{job}.pdf"


def _latexmk(src: Path, main_name: str, rc_dir: Path) -> None:
    rc = rc_dir / "latexmkrc"
    rc.write_text(LATEXMKRC)
    (src / "fig_tmp").mkdir(exist_ok=True)  # externalize prefix of the thesis corpus
    argv = [
        "latexmk",
        "-pdf",
        "-shell-escape",
        "-synctex=1",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-r",
        str(rc),
        f"-jobname={Path(main_name).stem}",
        main_name,
    ]
    env = TeXLive().environment(EPOCH, os.environ)
    r = run(argv, cwd=src, env=env)
    assert r.ok, r.output[-3000:]


@pytest.mark.parametrize(
    ("corpus", "variant"),
    [("thesis", "twoside"), ("thesis", "oneside"), ("hgb", None), ("pictures", None)],
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
    ref = latexmk(src, "main.tex", tmp_path)
    ours = tmp_path / "fi" / "main.pdf"
    report = compare_pdfs(ref, ours)
    sources = ["main.tex"] + [f"{inc.arg}.tex" for inc in analyse(Config(main=main_tex)).includes]
    compare_synctex(ref, ours, sources, src, report=report)
    print(report.summary())
    assert report.ok, report.summary()
    assert report.counts["synctex view"] >= 5 * len(sources) // 2
