#!/bin/bash
# S13 colour leak: plain pdflatex vs a run with a mylatexformat format (split at \begin{document}),
# without chapmk. Prints the red and black pixel counts of page 2 for both. Usage, from any
# directory, in an image with TeX (TeX Live or MiKTeX) and poppler:
#   bash tests/corpus/minimal/S13-format-state/colorleak-textpos/compare.sh
set -u
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d); cp "$here"/*.tex "$tmp"/; cd "$tmp"
pdflatex --version | head -1
flags=(-interaction=nonstopmode -halt-on-error)
mkdir plain fmtrun
for i in 1 2; do pdflatex "${flags[@]}" -output-directory=plain main.tex >/dev/null 2>&1; done
b=$(grep -n '\\begin{document}' main.tex | cut -d: -f1)
head -n $((b - 1)) main.tex > pre.tex; echo '\endofdump' >> pre.tex
pdflatex -ini "${flags[@]}" -jobname=pre "&pdflatex" mylatexformat.ltx pre.tex >/dev/null 2>&1 || echo "format build failed"
awk -v b=$b '{ if (NR < b) print ""; else if (NR == b) print "\\csname endofdump\\endcsname" $0; else print }' main.tex > run.tex
if pdflatex --version | grep -q MiKTeX; then fmt=(--undump="$tmp/pre.fmt"); else fmt=(-fmt=pre); export TEXFORMATS="$tmp:"; fi
for i in 1 2; do pdflatex "${fmt[@]}" "${flags[@]}" -output-directory=fmtrun -jobname=main run.tex >/dev/null 2>&1; done
for d in plain fmtrun; do
  pdftoppm -r 100 -f 2 -l 2 "$d/main.pdf" "$d/p"
  python3 - "$d" "$d"/p-*.ppm <<'PY'
import sys
data = open(sys.argv[2], "rb").read()
parts = data.split(maxsplit=4)  # P6 width height maxval pixels
px = parts[4]
red = black = 0
for i in range(0, len(px) - 2, 3):
    r, g, b = px[i], px[i + 1], px[i + 2]
    red += r > 150 and g < 100 and b < 100
    black += r < 100 and g < 100 and b < 100
print(f"{sys.argv[1]:7} page 2: red {red}, black {black}")
PY
done
