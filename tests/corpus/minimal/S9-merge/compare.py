"""S9: compare a merged PDF with the reference (PLAN §3.3 items 1-3)."""

import subprocess
import sys
import tempfile
from pathlib import Path

import pikepdf

ref_path, got_path = Path(sys.argv[1]), Path(sys.argv[2])


def resolve(pdf, pages, d):
    """named or explicit destination -> (page index, view)"""
    if isinstance(d, (pikepdf.String, str)):
        v = pikepdf.NameTree(pdf.Root.Names.Dests).get(str(d))
        if v is None:
            return ("MISSING", str(d))
        d = v.D if isinstance(v, pikepdf.Dictionary) else v
    return (pages.get(d[0].objgen, "?"), str(d[1]), [None if x is None else round(float(x), 3) for x in list(d)[2:]])


def facts(path: Path):
    pdf = pikepdf.open(path)
    pages = {p.objgen: i for i, p in enumerate(pdf.pages)}
    labels = [pikepdf.Page(p).label for p in pdf.pages]
    outline = []

    def walk(item, lvl):
        while item is not None:
            act = item.get("/A")
            tgt = resolve(pdf, pages, act.D) if act is not None else resolve(pdf, pages, item.Dest)
            outline.append((lvl, str(item.Title), int(item.get("/Count", 0)), tgt))
            walk(item.get("/First"), lvl + 1)
            item = item.get("/Next")

    walk(pdf.Root.Outlines.get("/First"), 0)
    links = []
    for i, p in enumerate(pdf.pages):
        for a in p.get("/Annots", []):
            if a.get("/Subtype") != "/Link":
                continue
            rect = [round(float(x), 3) for x in a.Rect]
            act = a.get("/A")
            if act is not None and act.get("/S") == "/URI":
                links.append((i, rect, "URI", str(act.URI)))
            else:
                links.append((i, rect, resolve(pdf, pages, act.D if act is not None else a.Dest)))
    return len(pdf.pages), labels, outline, links


def rasters(path: Path, d: Path) -> list[bytes]:
    subprocess.run(["pdftoppm", "-r", "150", str(path), str(d / "p")], check=True)
    return [f.read_bytes() for f in sorted(d.glob("p-*.ppm"))]


def texts(path: Path, n: int) -> list[str]:
    return [subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", str(path), "-"],
                           capture_output=True, text=True).stdout for i in range(1, n + 1)]


(rn, rl, ro, rk), (gn, gl, go, gk) = facts(ref_path), facts(got_path)
ok = True
def check(name, a, b):
    global ok
    same = a == b
    ok &= same
    print(f"  {name:12} {'identical' if same else 'DIFFERS'}")
    if not same:
        for x, y in zip(a if isinstance(a, list) else [a], b if isinstance(b, list) else [b]):
            if x != y:
                print(f"     ref: {x}\n     got: {y}")
                break


check("page count", rn, gn)
with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
    ra, ga = rasters(ref_path, Path(t1)), rasters(got_path, Path(t2))
check("raster", [i for i, (a, b) in enumerate(zip(ra, ga)) if a != b], [])
check("text", texts(ref_path, rn), texts(got_path, gn))
check("page labels", rl, gl)
check("outline", ro, go)
check("links", rk, gk)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
