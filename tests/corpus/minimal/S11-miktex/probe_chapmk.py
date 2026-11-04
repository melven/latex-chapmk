"""Spike S11: chapmk end to end under MiKTeX (prototype code, docs/spikes/S11.md).

Run in the MiKTeX image with the repository at /work:
    docker run --rm -v "$PWD":/work:ro -e PYTHONPATH=/work/src chapmk-miktex \
        python /work/tests/corpus/minimal/S11-miktex/probe_chapmk.py

A minimal MiKTeX adapter (subclass of the TeX Live one) with the two differences found by
run.sh: the format is passed as ``--undump=<absolute path>`` (MiKTeX ignores TEXFORMATS) and
``--max-print-line=10000`` replaces the environment variable. ``check`` samples SyncTeX with
absolute source paths (MiKTeX records Input paths without ``/./``; relative lookups find
nothing on both sides and would compare equal).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import chapmk.check
import chapmk.cli
from chapmk.texdist import TeXLive, tex_path

CORPUS = Path("/work/tests/corpus")
WORK = Path(os.environ.get("S11_WORK", "/tmp/s11-chapmk"))
EPOCH = "1700000000"


class MiKTeXProbe(TeXLive):
    name = "MiKTeX (spike)"

    def __init__(self) -> None:
        super().__init__()
        self.formats: Path | None = None

    def environment(
        self, epoch: int, base: Mapping[str, str], formats_dir: Path | None = None
    ) -> dict[str, str]:
        if formats_dir is not None:
            self.formats = formats_dir
        return super().environment(epoch, base, formats_dir)

    def pdflatex(self, tex_input: str, jobname: str, outdir: Path, fmt: str | None = None) -> list[str]:
        argv = super().pdflatex(tex_input, jobname, outdir, None)
        extra = ["--max-print-line=10000"]
        if fmt is not None:
            assert self.formats is not None
            extra.append(f"--undump={tex_path(self.formats / f'{fmt}.fmt')}")
        return [argv[0], *extra, *argv[1:]]

    def format_build(self, source: Path, jobname: str, outdir: Path) -> list[str]:
        argv = super().format_build(source, jobname, outdir)
        return [argv[0], "--max-print-line=10000", *argv[1:]]


_compare_synctex = chapmk.check.compare_synctex


def compare_synctex_abs(ref, got, sources, cwd, **kw):  # type: ignore[no-untyped-def]
    return _compare_synctex(ref, got, [str(Path(cwd) / s) for s in sources], cwd, **kw)


chapmk.check.compare_synctex = compare_synctex_abs
chapmk.cli.detect = lambda: MiKTeXProbe()  # type: ignore[assignment]


def prepare(name: str) -> Path:
    src = WORK / name
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(CORPUS / name, src, ignore=shutil.ignore_patterns("generate.py"))
    for tex in sorted(src.glob("fig/*.tex")):
        subprocess.run(["pdflatex", "-interaction=batchmode", tex.name], cwd=tex.parent,
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return src


def build(src: Path, label: str, *args: str) -> None:
    report = src.parent / f"{src.name}-report.json"
    report.unlink(missing_ok=True)
    rc = chapmk.cli.main(["build", "main.tex", "--check", "--report", str(report), *args], cwd=src)
    rep = json.loads(report.read_text()) if report.is_file() else {}
    sel = [r.get("selection") for r in rep.get("runs", [])]
    print(f"### {label}: rc={rc} mode={rep.get('mode')} reason={rep.get('reason')} "
          f"runs={len(sel)} selections={sel}", flush=True)


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, old
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    os.environ["SOURCE_DATE_EPOCH"] = EPOCH
    WORK.mkdir(parents=True, exist_ok=True)
    thesis = prepare("thesis")
    (thesis / "fig_tmp").mkdir(exist_ok=True)
    build(thesis, "thesis cold")
    ch3 = next(thesis.glob("chapters/ch3*.tex"))
    lines = ch3.read_text().split("\n")
    word = next(w for line in lines[3:] for w in line.split() if w.isalpha() and len(w) > 5)
    edit(ch3, word, word + "x")
    build(thesis, f"thesis typo in {ch3.name} ({word})")
    edit(ch3, "\\section", "\\clearpage\\null\\clearpage\\section")
    build(thesis, f"thesis page shift in {ch3.name}", "-j", "4")
    pictures = prepare("pictures")
    build(pictures, "pictures cold")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
