#!/usr/bin/env bash
# Spike S10: SyncTeX merge of two partial runs, verified with synctex view/edit against the
# full run (docs/spikes/S10.md). Uses the S9 document and merge.
# Usage (dev container, cwd = this directory): ./run.sh OUTDIR [badcount]
set -u
HERE=$(pwd); DOC="$HERE/../S9-merge"; OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT/full"
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000
PRE='\edef\sninekernel{\the\count10}\AddToHook{begindocument/before}{\RequirePackage{s9probe}}'
pass() { (cd "$DOC" && pdflatex -synctex=1 -interaction=nonstopmode -halt-on-error -output-directory="$1" -jobname=main "$PRE$2\\input{main.tex}" >"$1/pass.out" 2>&1) || echo "FAIL $1"; }
for i in 1 2 3; do pass "$OUT/full" ""; done
for r in A:u1 B:u2,u3; do d="$OUT/${r%%:*}"; mkdir -p "$d"; cp "$OUT"/full/*.aux "$OUT"/full/main.toc "$d/"; pass "$d" "\\includeonly{${r#*:}}"; done
SEGS="G0=A,U:u1.tex=A,G:u1.tex=A,U:u2.tex=B,G:u2.tex=A,U:u3.tex=B,G:u3.tex=A"
python3 -I "$DOC/merge.py" "$OUT/merged.pdf" "$SEGS" A="$OUT/A" B="$OUT/B"
# merged page order (run:index) from the page maps, same rule as merge.py
PAGES=$(python3 -I - "$SEGS" "$OUT" <<'PY'
import sys
segs = [s.split("=") for s in sys.argv[1].split(",")]
fpg = {r: [l.split(" ", 3) for l in open(f"{sys.argv[2]}/{r}/main.fpg").read().splitlines()] for r in {r for _, r in segs}}
print(",".join(f"{r}:{n}" for seg, r in segs for n, s, *_ in fpg[r] if s == seg))
PY
)
python3 -I "$HERE/merge_synctex.py" "$OUT/merged.synctex.gz" "$PAGES" A="$OUT/A" B="$OUT/B"
[ "${2:-}" = badcount ] && { zcat "$OUT/merged.synctex.gz" | sed 's/^Count:.*/Count:1/' | gzip >"$OUT/x.gz"; mv "$OUT/x.gz" "$OUT/merged.synctex.gz"; echo "(Count deliberately wrong)"; }
python3 -I "$HERE/verify.py" "$OUT/full/main.pdf" "$OUT/merged.pdf" "$DOC" main.tex u1.tex u2.tex u3.tex
