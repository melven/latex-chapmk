#!/usr/bin/env bash
# Spike S12, part 2: reference = the document with a real \tikzexternalize (shell escape,
# figure jobs); compared with the chapmk-style cache embedded by TikZ external's own code.
# Usage (dev container, cwd = this directory): ./run_ext.sh OUTDIR [SRCDIR]
set -u
HERE=$(pwd); OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT"
SRC=$(realpath "${2:-$HERE}")
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000
# the "user" document: externalize after \usepackage{tikz}
mkdir -p "$OUT/extsrc"; cp "$SRC"/*.tex "$OUT/extsrc/"
sed -i 's/^\\usepackage{tikz}$/\\usepackage{tikz}\\usetikzlibrary{external}\\tikzexternalize[prefix=figref\/]/' "$OUT/extsrc/main.tex"
grep -q tikzexternalize "$OUT/extsrc/main.tex" || { echo "no \\usepackage{tikz} line"; exit 1; }
timed() { local s; s=$(date +%s.%N); "$@"; echo "$(python3 -c "print(round($(date +%s.%N)-$s,2))")"; }
mkdir -p "$OUT/ref/figref"
for i in 1 2 3; do
  t=$(cd "$OUT/ref" && TEXINPUTS="$OUT/extsrc:" timed pdflatex -shell-escape -synctex=1 -interaction=nonstopmode \
      -halt-on-error main.tex >pass.out 2>&1; tail -1 pass.out)
  echo "  ref (externalize) pass $i: $(cd "$OUT/ref"; grep -m1 '^!' main.log) ${t}"
done
echo "  figures made by externalize: $(ls "$OUT"/ref/figref/*.pdf | wc -l)"
export TEXINPUTS="$SRC:$HERE:"
pass() {
  (cd "$1" && s=$(date +%s.%N) && pdflatex -synctex=1 -interaction=nonstopmode -halt-on-error -jobname=main \
     "\\PassOptionsToPackage{$2}{s12probe}\\AddToHook{begindocument/before}{\\RequirePackage{s12probe}}\\input{main.tex}" \
     >pass.out 2>&1 || echo "FAIL $1: $(grep -m1 '^!' main.log)"; echo "  $(basename "$1") $2: $(python3 -c "print(round($(date +%s.%N)-$s,2))") s")
}
for d in fill use; do mkdir -p "$OUT/$d"; cp "$OUT"/ref/*.aux "$OUT/ref/main.toc" "$OUT/$d/"; done
pass "$OUT/fill" cache
python3 -I "$HERE/split.py" "$OUT/fill" "$OUT/use/fig" ext | grep -c cached | sed 's/^/  exported: /'
pass "$OUT/use" cache,noexport,extinc
PYTHONPATH="$HERE/../../../../src" python3 "$HERE/compare.py" "$SRC" "$OUT/ref" "$OUT/use" main.pdf
python3 "$HERE/pages.py" "$OUT/ref/main.pdf" "$OUT/use/main.pdf"
