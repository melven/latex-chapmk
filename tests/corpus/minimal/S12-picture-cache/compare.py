"""S12: §3.3 comparison of a run against the reference (fastinc.check)."""

import shutil
import sys
from pathlib import Path

from fastinc.check import compare_pdfs, compare_synctex

src, ref, got, name = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
units = sorted(f.name for f in src.glob("*.tex") if f.name != "main.tex")
work = got / "cmp"
shutil.rmtree(work, ignore_errors=True)
work.mkdir()
for f in ["main.tex", *units]:
    shutil.copy(src / f, work / f)
shutil.copy(ref / "main.pdf", work / "ref.pdf")
shutil.copy(ref / "main.synctex.gz", work / "ref.synctex.gz")
shutil.copy(got / name, work / "got.pdf")
if (got / "main.synctex.gz").exists() and name == "main.pdf":
    shutil.copy(got / "main.synctex.gz", work / "got.synctex.gz")
r = compare_pdfs(work / "ref.pdf", work / "got.pdf")
if (work / "got.synctex.gz").exists():
    compare_synctex(work / "ref.pdf", work / "got.pdf", units, work, samples=40, report=r)
print(f"  {got.name}: {'IDENTICAL' if r.ok else 'DIFFERS'}")
for d in r.differences:
    print(f"    {d.item}: {d.detail[:300]}")
