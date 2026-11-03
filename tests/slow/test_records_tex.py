"""M2: chapmk.sty records in real runs (PLAN §6.4.2), run directories and the runner."""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pikepdf
import pytest

from chapmk.analysis import analyse
from chapmk.config import Config
from chapmk.fmt import ensure_format
from chapmk.layout import make_layout
from chapmk.records import read_run_records
from chapmk.runner import RunSpec, prepare_run_dir, run_batch
from chapmk.shadow import sync_project_shadow
from chapmk.texdist import detect

pytestmark = pytest.mark.slow
EPOCH = 1700000000


def setup(src: Path):  # type: ignore[no-untyped-def]
    cfg = Config(main=src / "main.tex")
    a = analyse(cfg)
    lay = make_layout(cfg, a)
    sync_project_shadow(a, lay.shadow_dir, lay.build_dir)
    dist = detect()
    env = dist.environment(EPOCH, os.environ, lay.fmt_dir)
    fmt = ensure_format(a, lay, dist, env)
    return a, lay, dist, env, fmt


def converge_full_run(a, lay, dist, env, fmt, passes: int = 3) -> Path:  # type: ignore[no-untyped-def]
    """Full runs (selection = all) with biber/makeindex, results copied to a canon dir."""
    canon = lay.build_dir / "canon"
    canon.mkdir(parents=True, exist_ok=True)
    for n in range(passes):
        prepare_run_dir(a, lay, RunSpec("full", None), canon_dir=canon)
        [r] = run_batch(a, lay, dist, env, [RunSpec("full", None)], fmt.name, jobs=1)
        assert r.ok, r.first_error
        if n == 0:
            subprocess.run(
                ["biber", "--output-directory", str(r.directory), "main"],
                cwd=lay.shadow_dir,
                env=env,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["makeindex", "-s", "nomencl.ist", "-o", "main.nls", "main.nlo"],
                cwd=r.directory,
                env=env,
                check=True,
                capture_output=True,
            )
        shutil.rmtree(canon)
        shutil.copytree(r.directory, canon)
    return canon


def page_hashes(pdf_path: Path, workdir: Path) -> dict[str, str]:
    """page label -> hash of a 60 dpi raster"""
    workdir.mkdir()
    subprocess.run(["pdftoppm", "-r", "60", "-gray", str(pdf_path), str(workdir / "p")], check=True)
    with pikepdf.open(pdf_path) as pdf:
        labels = [str(pikepdf.Page(p).label) for p in pdf.pages]
    files = sorted(workdir.glob("p-*.pgm"))
    return {
        lab: hashlib.sha1(f.read_bytes()).hexdigest() for lab, f in zip(labels, files, strict=True)
    }


def test_records_and_restore(copy_corpus) -> None:  # type: ignore[no-untyped-def]
    src = copy_corpus("thesis")
    a, lay, dist, env, fmt = setup(src)
    canon = converge_full_run(a, lay, dist, env, fmt)
    full = read_run_records(canon, a)

    # all segments in document order, units numbered like the analysis
    n = len(a.includes)
    expected = ["G0"] + [s for k in range(1, n + 1) for s in (f"U{k}", f"G{k}")]
    assert full.segments_in_order() == expected
    assert set(full.checkpoints) == {f"U{k}" for k in range(1, n + 1)}
    assert set(full.glue_exits) == {f"G{k}" for k in range(n + 1)}
    # page map: every page attributed; units start on their own pages
    assert [p.index for p in full.pages] == list(range(len(full.pages)))
    assert {p.segment for p in full.pages} >= {f"U{k}" for k in range(1, n + 1)}
    assert full.pages[0].segment == "G0" and full.pages[-1].segment == f"G{n}"
    # files attributed to their units, graphics included
    seg_files = {(s, f.rsplit("/", 1)[-1]) for s, f in full.files}
    assert ("U1", "ch1.tex") in seg_files and ("U1", "plot1.pdf") in seg_files
    # absolute sets (chapter counter resets the section counter), bookmark levels, nomencl
    assert full.absolute["U1"]
    assert sorted(set(full.bookmark_levels.values())) == [0, 1, 2]
    # counter registers and reset lists (M4): the chapter resets section, figure, ...
    chapter_resets = full.reset_registers("chapter")
    assert {full.counters[c][0] for c in ("section", "subsection", "figure")} <= chapter_resets
    assert full.counters["page"][0] == 0
    assert full.layout == {"twoside": 1, "openright": 1}  # scrbook defaults
    assert any(line.startswith("\\nomenclatureentry") for line in full.nomenclature["U1"])
    # checkpoint changes include the page counter (index 0)
    assert 0 in full.checkpoints["U3"]

    # partial run: ch3 and appA, the rest excluded and restored from the canonical aux files
    spec = RunSpec("partial", ("chapters/ch3", "chapters/appA"))
    prepare_run_dir(a, lay, spec, canon_dir=canon)
    [r] = run_batch(a, lay, dist, env, [spec], fmt.name, jobs=2)
    assert r.ok, r.first_error
    part = read_run_records(r.directory, a)
    assert part.segments_in_order() == expected
    for seg in expected:
        assert part.entry_state(seg) == full.entry_state(seg), seg
    # every partial page equals the full-run page with the same label
    ref = page_hashes(canon / "main.pdf", lay.build_dir / "h-full")
    got = page_hashes(r.directory / "main.pdf", lay.build_dir / "h-part")
    assert got and all(ref[label] == h for label, h in got.items())


def test_parallel_batch_and_error(copy_corpus) -> None:  # type: ignore[no-untyped-def]
    src = copy_corpus("hgb")
    a, lay, dist, env, fmt = setup(src)
    specs = [RunSpec(f"r{i}", (inc.arg,)) for i, inc in enumerate(a.includes)]
    specs.append(RunSpec("glue", ()))
    for spec in specs:
        prepare_run_dir(a, lay, spec)
    results = run_batch(a, lay, dist, env, specs, fmt.name, jobs=4)
    assert [r.spec for r in results] == specs and all(r.ok for r in results)
    (src / "chapters" / "usage.tex").write_text("\\chapter{Broken}\n\\undefinedmacro\n")
    sync_project_shadow(a, lay.shadow_dir, lay.build_dir)
    bad = RunSpec("bad", ("chapters/usage",))
    prepare_run_dir(a, lay, bad)
    [r] = run_batch(a, lay, dist, env, [bad], fmt.name, jobs=1)
    assert not r.ok and r.first_error and "usage.tex:2: Undefined control sequence" in r.first_error
