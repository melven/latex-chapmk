"""Benchmarks (design §8.4): wall times of T16 (cold), T1, T2, T4 for latexmk, ``chapmk -j 1``
and ``chapmk -j N`` on a generated large thesis, plus the time per build phase.

Run inside the dev container (no xdist, idle cores), e.g.::

    python tests/bench/run.py --out /tmp/bench --chapters 20 --scale 3 --jobs 4

Prints a Markdown report and writes ``<out>/bench.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent.parent / "src"), str(HERE.parent)]

from conftest import prepare_figures  # noqa: E402

from chapmk.cli import main  # noqa: E402
from chapmk.proc import run  # noqa: E402
from chapmk.texdist import TeXLive  # noqa: E402

EPOCH = 1700000000
PARA = "\n\n".join(["Additional text to make the chapter longer. " * 40] * 6)
LATEXMKRC = r"""
add_cus_dep('nlo', 'nls', 0, 'nlo2nls');
sub nlo2nls {
  my ($dir, $base) = ($_[0] =~ m{^(.*)/([^/]+)$}) ? ($1, $2) : ('.', $_[0]);
  return system("cd '$dir' && makeindex -s nomencl.ist -o '$base.nls' '$base.nlo'");
}
"""


def _generate(src: Path, chapters: int, scale: int) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "thesis_gen", HERE.parent / "corpus" / "thesis" / "generate.py"
    )
    assert spec and spec.loader
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.generate(src, chapters, scale)
    prepare_figures(src)


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, (path, old)
    path.write_text(text.replace(old, new, 1))


def _restore(cache: Path, live: Path) -> None:
    if live.exists():
        shutil.rmtree(live)
    shutil.copytree(cache, live, symlinks=True)


def chapmk(src: Path, *args: str) -> tuple[float, dict[str, Any]]:
    report = src.parent / "report.json"
    report.unlink(missing_ok=True)
    start = time.monotonic()
    rc = main(["build", "main.tex", "--report", str(report), *args], cwd=src)
    seconds = time.monotonic() - start
    assert rc == 0, f"chapmk {args} failed"
    return seconds, json.loads(report.read_text())


def latexmk(src: Path) -> float:
    rc = src.parent / "latexmkrc"
    rc.write_text(LATEXMKRC)
    (src.parent / "lmk-out" / "chapters").mkdir(parents=True, exist_ok=True)  # \include (S2)
    argv = [
        "latexmk",
        "-pdf",
        "-synctex=1",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-outdir={src.parent / 'lmk-out'}",
        "-r",
        str(rc),
        "-usepretex=\\RequirePackage{chapmk-ini}",
        "-jobname=main",  # -usepretex makes the job name texput otherwise
        "main.tex",
    ]
    start = time.monotonic()
    r = run(argv, cwd=src, env=TeXLive().environment(EPOCH, os.environ))
    assert r.ok, r.output[-2000:]
    return time.monotonic() - start


def scenarios(n: int) -> dict[str, Callable[[Path], None]]:
    mid = f"ch{max(1, n // 2)}"
    return {
        "T1 typo": lambda s: _edit(
            s / "chapters" / f"{mid}.tex", "Further reading:", "Furhter reading:"
        ),
        "T2 page count": lambda s: _edit(
            s / "chapters" / "ch3.tex",
            "\\section*{Remarks on ch3}",
            PARA + "\n\\section*{Remarks on ch3}",
        ),
        "T4 citation": lambda s: _edit(
            s / "chapters" / "ch4.tex",
            "Further reading: \\cite{ref20}.",
            "Further reading: \\cite{ref20,ref41}.",
        ),
    }


def breakdown(rep: dict[str, Any]) -> dict[str, Any]:
    tex: dict[str, float] = {}
    for r in rep.get("runs", []):
        for k, v in (r.get("tex") or {}).items():
            tex[k] = round(tex.get(k, 0.0) + v, 2)
    batches = len({r.get("batch") for r in rep.get("runs", [])})
    return {
        "runs": len(rep.get("runs", [])),
        "batches": batches,
        "driver": rep.get("timings", {}),
        "tex_sum": tex,
    }


def bench(out: Path, chapters: int, scale: int, jobs: int) -> dict[str, Any]:
    os.environ["SOURCE_DATE_EPOCH"] = str(EPOCH)
    pristine = out / "pristine"
    if pristine.exists():
        shutil.rmtree(pristine)
    _generate(pristine, chapters, scale)
    live = out / "live" / "src"
    results: dict[str, Any] = {"chapters": chapters, "scale": scale, "jobs": jobs, "rows": {}}
    rows = results["rows"]

    # T16: cold builds and latexmk from scratch
    lmk = out / "lmk" / "src"
    if lmk.parent.exists():
        shutil.rmtree(lmk.parent)
    _restore(pristine, lmk)
    t_lmk = latexmk(lmk)
    lmk_cache = out / "lmk-cache"
    if lmk_cache.exists():
        shutil.rmtree(lmk_cache)
    shutil.copytree(lmk.parent, lmk_cache, symlinks=True)
    row: dict[str, Any] = {"latexmk": round(t_lmk, 1)}
    _restore(pristine, live)
    t, _ = chapmk(live, "--full")
    row["--full"] = round(t, 1)
    for j in (1, jobs):  # the -jN cold state is the start of the edit scenarios
        _restore(pristine, live)
        t, rep = chapmk(live, "-j", str(j))
        row[f"-j{j}"] = round(t, 1)
        row[f"-j{j} breakdown"] = breakdown(rep)
    import pikepdf

    with pikepdf.open(live / "main.pdf") as pdf:
        pages = len(pdf.pages)
    rows["T16 cold"] = row
    cache = out / "cache"
    if cache.exists():
        shutil.rmtree(cache)
    shutil.copytree(live.parent, cache, symlinks=True)

    for name, apply in scenarios(chapters).items():
        row = {}
        if (out / "lmk").exists():
            shutil.rmtree(out / "lmk")
        shutil.copytree(lmk_cache, out / "lmk", symlinks=True)
        apply(lmk)
        row["latexmk"] = round(latexmk(lmk), 1)
        for j in (1, jobs):
            _restore(cache, live.parent)
            apply(live)
            t, rep = chapmk(live, "-j", str(j))
            row[f"-j{j}"] = round(t, 1)
            row[f"-j{j} breakdown"] = breakdown(rep)
            row[f"-j{j} compiled"] = len(rep["compiled"])
        rows[name] = row
    results["pages"] = pages
    return results


def markdown(res: dict[str, Any]) -> str:
    j = res["jobs"]
    lines = [
        f"Thesis generator: {res['chapters']} chapters, scale {res['scale']} "
        f"({res['pages']} pages); -j {j}. T16: --full {res['rows']['T16 cold']['--full']} s.",
        "",
        f"| scenario | latexmk | chapmk -j 1 | chapmk -j {j} |",
        "|---|---|---|---|",
    ]
    for name, row in res["rows"].items():
        b1, bn = row["-j1 breakdown"], row[f"-j{j} breakdown"]
        lines.append(
            f"| {name} | {row['latexmk']} s | {row['-j1']} s ({b1['runs']} runs) | "
            f"{row[f'-j{j}']} s ({bn['runs']} runs, {bn['batches']} batches) |"
        )
    lines += ["", "Breakdown (driver phases: wall s; TeX: summed over runs, s):", ""]
    for name, row in res["rows"].items():
        for key in ("-j1", f"-j{j}"):
            b = row[f"{key} breakdown"]
            drv = ", ".join(
                f"{k} {v:.1f}" for k, v in sorted(b["driver"].items(), key=lambda x: -x[1])
            )
            tex = ", ".join(f"{k} {v:.1f}" for k, v in b["tex_sum"].items())
            lines.append(f"- {name} {key}: driver: {drv}; TeX: {tex}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--chapters", type=int, default=20)
    ap.add_argument("--scale", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    res = bench(a.out.resolve(), a.chapters, a.scale, a.jobs)
    (a.out / "bench.json").write_text(json.dumps(res, indent=1))
    print(markdown(res))
