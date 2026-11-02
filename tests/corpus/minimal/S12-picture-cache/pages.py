"""S12: per-page raster difference (pixels, max delta) and text equality of two PDFs."""
import subprocess, sys, tempfile
from pathlib import Path
from PIL import Image, ImageChops
a, b = sys.argv[1], sys.argv[2]
with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    subprocess.run(["pdftoppm", "-r", "150", a, str(t / "a")], check=True)
    subprocess.run(["pdftoppm", "-r", "150", b, str(t / "b")], check=True)
    pa, pb = sorted(t.glob("a-*.ppm")), sorted(t.glob("b-*.ppm"))
    print("pages", len(pa), len(pb))
    for i, (x, y) in enumerate(zip(pa, pb), 1):
        d = ImageChops.difference(Image.open(x).convert("RGB"), Image.open(y).convert("RGB")).convert("L")
        hist = d.histogram(); n = sum(hist[1:]); mx = max((v for v in range(256) if hist[v]), default=0)
        ta = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", a, "-"], capture_output=True, text=True).stdout
        tb = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", b, "-"], capture_output=True, text=True).stdout
        tr = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), a, "-"], capture_output=True, text=True).stdout
        tg = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), b, "-"], capture_output=True, text=True).stdout
        if n or ta != tb or tr != tg:
            print(f"  page {i}: {n} px (max {mx}), layout text {'same' if ta == tb else 'DIFFERS'}, raw text {'same' if tr == tg else 'DIFFERS'}")
