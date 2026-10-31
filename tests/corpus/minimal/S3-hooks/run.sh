#!/usr/bin/env bash
# Spike S3: hook order around \include (docs/spikes/S3.md). Usage: ./run.sh OUTDIR
set -u
HERE=$(pwd); OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT/tmp"
(cd "$OUT/tmp" && pdflatex -interaction=batchmode "$HERE/fig.tex" >/dev/null && cp fig.pdf "$OUT/a.pdf")
export TEXINPUTS="$OUT:"   # finds a.pdf without writing into the source dir
run() {  # NAME INCLUDEONLY
  mkdir -p "$OUT/$1"; cp "$OUT"/full/*.aux "$OUT/$1/" 2>/dev/null
  pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$OUT/$1" -jobname=main \
    "$2\\input{main.tex}" >/dev/null 2>&1 || echo "FAIL $1"
  echo "== $1 ($2)"; grep -o 'S3EVENT.*' "$OUT/$1/main.log" | sed 's/S3EVENT /  /'
}
run full ""
run full ""
run partial '\includeonly{u1,u3}'
