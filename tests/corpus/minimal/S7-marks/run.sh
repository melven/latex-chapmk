#!/usr/bin/env bash
# Spike S7: running heads (marks) on unit pages, partial vs full runs (docs/spikes/S7.md).
# Usage (dev container, cwd = this directory): ./run.sh OUTDIR
set -u
HERE=$(pwd); OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT/full"
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1
pass() { pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$1" -jobname=main "$2\\input{main.tex}" >/dev/null 2>&1 || echo "FAIL $1"; }
for i in 1 2 3; do pass "$OUT/full" ""; done
for u in u1 u2 u3 u4; do d="$OUT/p-$u"; mkdir -p "$d"; cp "$OUT"/full/*.aux "$d/"; pass "$d" "\\includeonly{$u}"; done
python3 -I "$HERE/pagecmp.py" "$OUT" full p-u1 p-u2 p-u3 p-u4
echo "== with s7marks (mark state restored for excluded units)"
F="$OUT/full-m"; mkdir -p "$F"; for i in 1 2 3; do pass "$F" '\AddToHook{begindocument/before}{\RequirePackage{s7marks}}'; done
for u in u1 u2 u3 u4; do d="$OUT/m-$u"; mkdir -p "$d"; cp "$F"/*.aux "$d/"; pass "$d" "\\AddToHook{begindocument/before}{\\RequirePackage{s7marks}}\\includeonly{$u}"; done
python3 -I "$HERE/pagecmp.py" "$OUT" full-m m-u1 m-u2 m-u3 m-u4
# first text line (running head) of each differing page, full vs partial
python3 -I - "$OUT" <<'PY'
import subprocess, sys, pikepdf
from pathlib import Path
o = Path(sys.argv[1])
def heads(d):
    pdf = pikepdf.open(o / d / "main.pdf")
    res = {}
    for i, p in enumerate(pdf.pages):
        t = subprocess.run(["pdftotext", "-f", str(i + 1), "-l", str(i + 1), "-layout", str(o / d / "main.pdf"), "-"],
                           capture_output=True, text=True).stdout.strip().splitlines()
        res[pikepdf.Page(p).label] = " ".join(t[0].split()) if t else ""
    return res
full = heads("full")
for d in ("p-u1", "p-u2", "p-u3", "p-u4"):
    for lab, h in heads(d).items():
        if full.get(lab) != h:
            print(f"{d} page {lab}: head full={full.get(lab)!r} partial={h!r}")
PY
