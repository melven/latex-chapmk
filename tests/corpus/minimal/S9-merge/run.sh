#!/usr/bin/env bash
# Spike S9: merge two partial runs into one PDF and compare with the full run
# (docs/spikes/S9.md). Usage (dev container, cwd = this directory): ./run.sh OUTDIR
set -u
HERE=$(pwd); OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT/full"
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000
PRE='\edef\sninekernel{\the\count10}\AddToHook{begindocument/before}{\RequirePackage{s9probe}}'
pass() { pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$1" -jobname=main "$PRE$2\\input{main.tex}" >"$1/pass.out" 2>&1 || echo "FAIL $1: $(grep -m1 '^!' "$1/main.log")"; }
for i in 1 2 3; do pass "$OUT/full" ""; done
# partial runs from the converged state (as the canonical state would provide)
for r in A:u1 B:u2,u3; do d="$OUT/${r%%:*}"; mkdir -p "$d"; cp "$OUT"/full/*.aux "$OUT"/full/main.toc "$d/"; pass "$d" "\\includeonly{${r#*:}}"; done
SEGS="G0=A,U:u1.tex=A,G:u1.tex=A,U:u2.tex=B,G:u2.tex=A,U:u3.tex=B,G:u3.tex=A"
python3 -I "$HERE/merge.py" "$OUT/merged.pdf" "$SEGS" A="$OUT/A" B="$OUT/B"
python3 -I "$HERE/compare.py" "$OUT/full/main.pdf" "$OUT/merged.pdf"
