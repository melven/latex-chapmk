#!/usr/bin/env bash
# Spike S6: hyperref destinations, dummy/duplicate destinations, anchors, \HyPL@Entry,
# \BKM@entry (docs/spikes/S6.md). Usage (dev container, cwd = this directory): ./run.sh OUTDIR
set -u
HERE=$(pwd); OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT/full"
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000
pass() { pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$1" -jobname=main "$2\\input{main.tex}" >/dev/null 2>&1 || echo "FAIL $1"; }
for i in 1 2 3; do pass "$OUT/full" ""; done
mkdir -p "$OUT/p-u2"; cp "$OUT"/full/*.aux "$OUT"/full/main.toc "$OUT/p-u2/"; pass "$OUT/p-u2" '\includeonly{u2}'
for d in full p-u2; do
  echo "=================== $d"
  echo "-- log: dest / duplicate warnings"; grep -h -A1 "pdfTeX warning" "$OUT/$d/main.log" | grep -v "^--" | sed 's/^/  /'
  echo "-- main.aux: BKM / HyPL / fastinc-relevant lines"; grep -E "BKM@entry|HyPL@Entry|abspage" "$OUT/$d/main.aux" | sed 's/^/  /'
  echo "-- unit aux: newlabel (u1)"; grep newlabel "$OUT/$d/u1.aux" | sed 's/^/  /'
  python3 -I "$HERE/inspect.py" "$OUT/$d/main.pdf"
done
