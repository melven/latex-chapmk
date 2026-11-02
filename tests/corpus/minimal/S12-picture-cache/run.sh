#!/usr/bin/env bash
# Spike S12: picture cache prototype (docs/spikes/S12.md).
# Usage (dev container, cwd = this directory): ./run.sh OUTDIR [SRCDIR]
# SRCDIR: document (main.tex + units), default this directory; e.g. from gen_stress.py.
set -u
HERE=$(pwd); OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT"
SRC=$(realpath "${2:-$HERE}")
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000 TEXINPUTS="$SRC:$HERE:"
# pass DIR OPTION [extra code]: one pdflatex run in DIR (cwd), prints the TeX time
pass() {
  (cd "$1" && s=$(date +%s.%N) && pdflatex -synctex=1 -interaction=nonstopmode -halt-on-error -jobname=main \
     "${S12_PRE:-}\\PassOptionsToPackage{$2${S12_OPT:-}}{s12probe}\\AddToHook{begindocument/before}{\\RequirePackage{s12probe}}${3:-}\\input{main.tex}" \
     >pass.out 2>&1 || echo "FAIL $1: $(grep -m1 '^!' main.log)"; echo "  $(basename "$1") $2: $(python3 -c "print(round($(date +%s.%N)-$s,2))") s")
}
mkdir -p "$OUT/ref"; for i in 1 2 3; do pass "$OUT/ref" inline; done
for d in fill use; do mkdir -p "$OUT/$d"; cp "$OUT"/ref/*.aux "$OUT/ref/main.toc" "$OUT/$d/"; done
echo "fill run (empty cache):"; pass "$OUT/fill" cache
python3 -I "$HERE/split.py" "$OUT/fill" "$OUT/use/fig"
echo "use run (cache from fill):"; pass "$OUT/use" cache
python3 -I "$HERE/split.py" "$OUT/use" "$OUT/use/fig-new"
mkdir -p "$OUT/use2"; cp "$OUT"/ref/*.aux "$OUT/ref/main.toc" "$OUT/use2/"; cp -r "$OUT/use/fig" "$OUT/use2/"
echo "use run without export:"; pass "$OUT/use2" cache,noexport
echo "compare fill (extra pages removed) and use with ref:"
PYTHONPATH="$HERE/../../../../src" python3 "$HERE/compare.py" "$SRC" "$OUT/ref" "$OUT/fill" clean.pdf
PYTHONPATH="$HERE/../../../../src" python3 "$HERE/compare.py" "$SRC" "$OUT/ref" "$OUT/use" clean.pdf
PYTHONPATH="$HERE/../../../../src" python3 "$HERE/compare.py" "$SRC" "$OUT/ref" "$OUT/use2" main.pdf
