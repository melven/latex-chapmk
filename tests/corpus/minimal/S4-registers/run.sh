#!/usr/bin/env bash
# Spike S4: \count register vectors at segment boundaries, full vs partial runs
# (docs/spikes/S4.md). Usage (dev container, cwd = this directory): ./run.sh OUTDIR [norestore|restore]
set -u
HERE=$(pwd); OUT=$(realpath -m "${1:?outdir}"); MODE=${2:-norestore}   # norestore | restore
rm -rf "$OUT"; mkdir -p "$OUT/src/fig" "$OUT/tmp"
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000
cp "$HERE"/*.tex "$HERE"/*.sty "$HERE"/thesis.bib "$OUT/src/"
(cd "$OUT/tmp" && pdflatex -interaction=batchmode "$HERE/fig.tex" >/dev/null && mv fig.pdf "$OUT/src/fig/a.pdf")
# externalize neutralisation (PLAN §6.4.3), injected before \documentclass
OPT='\edef\sfourkernel{\the\count10}'; [ "$MODE" = restore ] && OPT="$OPT"'\PassOptionsToPackage{restore}{s4probe}'
NEUT="$OPT"'\AddToHook{file/after/tikzlibraryexternal.code.tex}{\renewcommand\tikzexternalize[1][]{}\let\tikzexternalenable\relax\let\tikzexternaldisable\relax}'
pass() {  # OUTDIR INCLUDEONLY-OR-EMPTY
  local io=""; [ "$2" != "-" ] && io="\\includeonly{$2}"
  (cd "$OUT/src" && pdflatex -interaction=nonstopmode -halt-on-error -file-line-error \
     -output-directory="$1" -jobname=main "$NEUT$io\\input{main.tex}" >"$1/pass.out" 2>&1) \
    || echo "  FAIL $1: $(grep -m1 -E '^!|^[^ ]*:[0-9]+: ' "$1/main.log")"
}
F="$OUT/full"; mkdir -p "$F"
pass "$F" -; (cd "$OUT/src" && biber --output-directory "$F" main >/dev/null); (cd "$F" && makeindex -s nomencl.ist -o main.nls main.nlo >/dev/null 2>&1)
for i in 1 2 3; do pass "$F" -; done
echo "full: $(pdfinfo "$F/main.pdf" | awk '/^Pages/{print $2}') pages, \\count10=$(head -1 "$F/main.s4v" | tr ',' '\n' | sed -n 11p)"
for sel in u1 u2 u3 u4 "" u1,u3; do
  d="$OUT/p-${sel:-none}"; mkdir -p "$d"
  cp "$F"/main.{aux,toc,lof,lot,loalg,tdo,bbl,nls} "$F"/u*.aux "$d/" 2>/dev/null
  pass "$d" "$sel"
done
python3 -I "$HERE/analyze.py" "$OUT" "$(kpsewhich -var-value TEXMFSYSVAR)/web2c/pdftex/pdflatex.log"
python3 -I "$HERE/pagecmp.py" "$OUT" full $(cd "$OUT" && ls -d p-*)
