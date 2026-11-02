#!/usr/bin/env bash
# Spike S12: one stress document per picture kind (2 units x 9 pictures), run.sh on each,
# then per-page differences of the cache run against the inline reference.
# Usage (dev container, cwd = this directory): ./kinds.sh OUTDIR
set -u
OUT=$(realpath -m "${1:?outdir}"); mkdir -p "$OUT"
for k in plot pgfplots opacity shading pattern graph image scaled; do
  python3 gen_stress.py "$OUT/k-$k-src" 2 9 "$k" >/dev/null
  S12_OPT=,natural ./run.sh "$OUT/k-$k" "$OUT/k-$k-src" >"$OUT/k-$k.txt" 2>&1
  echo "== $k: $(grep -c ': cached' "$OUT/k-$k.txt") cached, $(grep -c 'not cached' "$OUT/k-$k.txt") not; $(grep 'use2:' "$OUT/k-$k.txt")"
  python3 pages.py "$OUT/k-$k/ref/main.pdf" "$OUT/k-$k/use2/main.pdf" | grep page
done
