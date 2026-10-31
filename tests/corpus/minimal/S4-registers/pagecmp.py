"""S4: compare partial-run pages with the full-run page of the same label (60 dpi, gray)."""
import subprocess, sys, pikepdf, hashlib
from pathlib import Path
o = Path(sys.argv[1])
def pages(d):
    pdf = pikepdf.open(d / "main.pdf"); n = len(pdf.pages)
    labels = [pikepdf.Page(p).label for p in pdf.pages]
    subprocess.run(["pdftoppm", "-r", "60", "-gray", str(d / "main.pdf"), str(d / "cmp")], check=True)
    files = sorted(d.glob("cmp-*.pgm"))
    return {lab: hashlib.sha1(f.read_bytes()).hexdigest() for lab, f in zip(labels, files)}, n
full, nf = pages(o / sys.argv[2])
for v in sys.argv[3:]:
    part, n = pages(o / v)
    same = [l for l in part if full.get(l) == part[l]]
    diff = [l for l in part if full.get(l) != part[l]]
    print(f"{v}: {n} pages, identical to full-run page with same label: {len(same)}, differing: {diff}")
