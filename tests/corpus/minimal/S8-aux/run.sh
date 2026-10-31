#!/usr/bin/env bash
# Spike S8: inventory of aux line kinds on the S4 document (docs/spikes/S8.md).
# Usage (dev container, cwd = this directory): ./run.sh OUTDIR
set -u
HERE=$(pwd); SRC4="$HERE/../S4-registers"; OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT/src/fig" "$OUT/tmp" "$OUT/full"
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000
cp "$SRC4"/*.tex "$SRC4"/thesis.bib "$HERE/s8probe.sty" "$OUT/src/"
sed -i 's/\\usepackage{s4probe}/\\usepackage{s8probe}/' "$OUT/src/main.tex"
(cd "$OUT/tmp" && pdflatex -interaction=batchmode "$SRC4/fig.tex" >/dev/null && mv fig.pdf "$OUT/src/fig/a.pdf")
NEUT='\AddToHook{file/after/tikzlibraryexternal.code.tex}{\renewcommand\tikzexternalize[1][]{}\let\tikzexternalenable\relax\let\tikzexternaldisable\relax}'
pass() { (cd "$OUT/src" && pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$1" -jobname=main "$NEUT$2\\input{main.tex}" >/dev/null 2>&1) || echo "FAIL $1"; }
F="$OUT/full"; pass "$F" ""; (cd "$OUT/src" && biber --output-directory "$F" main >/dev/null); (cd "$F" && makeindex -s nomencl.ist -o main.nls main.nlo >/dev/null 2>&1)
for i in 1 2 3; do pass "$F" ""; done
python3 -I "$HERE/inventory.py" "$F"
for sel in u4 u1,u3; do
  d="$OUT/p-$sel"; mkdir -p "$d"; cp "$F"/main.{aux,toc,lof,lot,loalg,lol,tdo,bbl,nls} "$F"/u*.aux "$d/" 2>/dev/null
  pass "$d" "\\includeonly{$sel}"; echo "######## partial run {$sel}"; python3 -I "$HERE/inventory.py" "$d" main-only
done
