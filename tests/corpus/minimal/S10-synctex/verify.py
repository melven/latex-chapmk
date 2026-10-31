"""S10: compare synctex view/edit results of the merged PDF with the full run (PLAN §3.3 item 4)."""

import re
import subprocess
import sys
from pathlib import Path

ref_pdf, got_pdf, srcdir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
files = sys.argv[4:]


def run(args):
    r = subprocess.run(["synctex", *args], capture_output=True, text=True, cwd=srcdir)
    return [l for l in r.stdout.splitlines() if re.match(r"^(Page|x|y|h|v|W|H|Input|Line|Column|Offset|Context):", l)]


views = edits = vbad = ebad = 0
for f in files:
    n = len((srcdir / f).read_text().splitlines())
    for line in range(1, n + 1):
        a = run(["view", "-i", f"{line}:1:{f}", "-o", str(ref_pdf)])
        b = run(["view", "-i", f"{line}:1:{f}", "-o", str(got_pdf)])
        if not a:
            continue
        views += 1
        if a != b:
            vbad += 1
            print(f"  view {f}:{line}\n     ref {a[:4]}\n     got {b[:4]}")
        # inverse search at the first result's position
        pg = next(l for l in a if l.startswith("Page:")).split(":")[1]
        x = next(l for l in a if l.startswith("x:")).split(":")[1]
        y = next(l for l in a if l.startswith("y:")).split(":")[1]
        ea = run(["edit", "-o", f"{pg}:{x}:{y}:{ref_pdf}"])
        eb = run(["edit", "-o", f"{pg}:{x}:{y}:{got_pdf}"])
        edits += 1
        if ea != eb:
            ebad += 1
            print(f"  edit p{pg} ({x},{y})\n     ref {ea[:2]}\n     got {eb[:2]}")
print(f"synctex view: {views - vbad}/{views} identical; synctex edit: {edits - ebad}/{edits} identical")
print("RESULT:", "PASS" if views and not vbad and not ebad else "FAIL")
