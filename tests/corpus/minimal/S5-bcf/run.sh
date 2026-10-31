#!/usr/bin/env bash
# Spike S5: biblatex .bcf after \includeonly runs (docs/spikes/S5.md). Usage: ./run.sh OUTDIR
set -u
OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT/full"
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1
pass() { pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$1" -jobname=main "$2\\input{main.tex}" >/dev/null 2>&1 || echo "FAIL $1"; }
keys() { grep -o '<bcf:citekey[^>]*>[^<]*</bcf:citekey>' "$1/main.bcf" | sed -E 's|<bcf:citekey order="([0-9]+)" intorder="([0-9]+)">([^<]*)</bcf:citekey>|\3(\1.\2)|' | tr '\n' ' '; }
pass "$OUT/full" ""; biber --output-directory "$OUT/full" main >/dev/null; pass "$OUT/full" ""; pass "$OUT/full" ""
echo "full:    $(keys "$OUT/full")"
for f in main u1 u2 u3; do echo "  $f.aux: $(grep -o '\\abx@aux@cite{[^}]*}{[^}]*}' "$OUT/full/$f.aux" | tr '\n' ' ')"; done
for sel in u1 u2 u3 "" u1,u3; do
  d="$OUT/p-${sel:-none}"; mkdir -p "$d"; cp "$OUT"/full/*.aux "$OUT/full/main.bbl" "$d/"
  pass "$d" "\\includeonly{$sel}"; echo "p-${sel:-none}: $(keys "$d")"
done
diff <(grep -v '<bcf:citekey' "$OUT/full/main.bcf") <(grep -v '<bcf:citekey' "$OUT/p-u2/main.bcf") >/dev/null \
  && echo "bcf outside citekeys: identical (full vs p-u2)" || echo "bcf outside citekeys: DIFFERS"
