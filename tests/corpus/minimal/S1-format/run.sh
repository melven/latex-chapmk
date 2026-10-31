#!/usr/bin/env bash
# Spike S1: mylatexformat with the thesis preamble (docs/spikes/S1.md).
# Usage (inside the dev container, cwd = this directory): ./run.sh OUTDIR [SPLIT...]
#   Builds a plain reference and, for each SPLIT line s, a format from lines 1..s-1
#   plus a run main with lines 1..s-1 blanked and line s prefixed by
#   \csname endofdump\endcsname. Compares pages (pdftoppm -r 150), text and SyncTeX.
set -u
OUT=$(realpath -m "${1:?outdir}"); shift
SPLITS=("${@:-41}")
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000
FLAGS=(-interaction=nonstopmode -halt-on-error -file-line-error -synctex=1 -recorder)
B=$(grep -n '\\begin{document}' main.tex | head -1 | cut -d: -f1)

# build OUTSUB TEXFILE [pdflatex options...]: pdflatex, biber, makeindex, pdflatex x2
build() {
  local d=$1 tex=$2; shift 2
  mkdir -p "$d"
  for pass in 1 2 3; do
    pdflatex "$@" "${FLAGS[@]}" -output-directory="$d" -jobname=main "$tex" >"$d/pass$pass.out" 2>&1 \
      || { echo "  FAIL pass $pass: $(grep -m1 -E '^!|^[^ ]*:[0-9]+: ' "$d/main.log" 2>/dev/null || tail -1 "$d/pass$pass.out")"; return 1; }
    if [ $pass = 1 ]; then
      biber --output-directory "$d" main >"$d/biber.out" 2>&1 || echo "  biber failed"
      # makeindex refuses absolute output paths (openout_any = p): run in the output dir
      [ -f "$d/main.nlo" ] && (cd "$d" && makeindex -s nomencl.ist -o main.nls main.nlo >mi.out 2>&1)
    fi
  done
  echo "  ok: $(pdfinfo "$d/main.pdf" | awk '/^Pages/{print $2}') pages"
}

raster() { rm -f "$1"/pg-*; pdftoppm -r 150 "$1/main.pdf" "$1/pg"; pdftotext -layout "$1/main.pdf" "$1/main.txt"; }

compare() {  # REF VARIANT
  local n=0 bad=0
  for f in "$1"/pg-*; do n=$((n+1)); cmp -s "$f" "$2/$(basename "$f")" || { bad=$((bad+1)); echo "  page differs: $(basename "$f")"; }; done
  [ "$(ls "$1"/pg-* | wc -l)" = "$(ls "$2"/pg-* | wc -l)" ] || echo "  page COUNT differs"
  echo "  raster: $((n-bad))/$n pages identical"
  cmp -s "$1/main.txt" "$2/main.txt" && echo "  text: identical" || echo "  text: DIFFERS"
}

synctex_probe() {  # DIR INPUTNAME -> "line page x y" for sampled body lines
  for l in $(seq $((B+6)) 2 $((B+14))); do
    synctex view -i "$l:1:$2" -o "$1/main.pdf" 2>/dev/null \
      | awk -v l="$l" '/^Page:/{p=$0}/^h:/{h=$0}/^v:/{print l, p, h, $0; exit}'
  done
}

echo "== reference (plain pdflatex)"
build "$OUT/ref" main.tex && raster "$OUT/ref"
synctex_probe "$OUT/ref" main.tex >"$OUT/ref/synctex.txt"

for s in "${SPLITS[@]}"; do
  d="$OUT/s$s"; mkdir -p "$d"
  echo "== split before line $s: $(sed -n "${s}p" main.tex | cut -c1-60)"
  { head -n $((s-1)) main.tex; echo '\endofdump'; } >"$d/pre.tex"
  pdflatex -ini -jobname=pre -output-directory="$d" "&pdflatex" mylatexformat.ltx "$d/pre.tex" >"$d/fmt.out" 2>&1 \
    || { echo "  FORMAT FAIL: $(grep -m1 '^!' "$d/pre.log")"; continue; }
  echo "  format: $(du -k "$d/pre.fmt" | cut -f1) KiB"
  { for _ in $(seq 1 $((s-1))); do echo; done
    printf '%s' '\csname endofdump\endcsname'; tail -n +"$s" main.tex; } >"$d/main.tex"
  # -fmt with an absolute path breaks -recorder (temp .fls name is built from it): use TEXFORMATS
  TEXFORMATS="$d:" build "$d/run" "$d/main.tex" -fmt=pre || continue
  raster "$d/run"; compare "$OUT/ref" "$d/run"
  synctex_probe "$d/run" "$d/main.tex" >"$d/run/synctex.txt"
  diff -q "$OUT/ref/synctex.txt" "$d/run/synctex.txt" >/dev/null \
    && echo "  synctex view: identical ($(wc -l <"$d/run/synctex.txt") probes)" \
    || { echo "  synctex view: DIFFERS"; diff "$OUT/ref/synctex.txt" "$d/run/synctex.txt" | head -6; }
  ls "$d"/run | grep -E '^pre\.' | sed 's/^/  stray file: /'
  grep -h -E 'mylatexformat\)Info: start reading' "$d/run/main.log" | sed 's/^/  /'
done
