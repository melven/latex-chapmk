#!/usr/bin/env bash
# S15: where the first-page material goes. Run in the dev image from the repository root:
#   bash tests/corpus/minimal/S15-first-page/run.sh
# 1. plain pdflatex: full build and \includeonly{c}; the first records of each page's sheet
# 2. chapmk: cold build, edit of c (a run of c only), records per page against --check's
#    reference (equal with the S15 extra page)
set -u
w=$(mktemp -d); cp tests/corpus/minimal/S15-first-page/*.tex "$w"/; cd "$w"
export SOURCE_DATE_EPOCH=1700000000
first() { zcat main.synctex.gz | awk '/^\{/{pg=$0; n=0} /^[\[(hv]/{ if (n++ < 3) print "  " pg, $0 }'; }
pdflatex -synctex=1 -interaction=batchmode main.tex >/dev/null; pdflatex -synctex=1 -interaction=batchmode main.tex >/dev/null
echo "full build:"; first | head -9
sed -i 's/\\begin{document}/\\includeonly{c}\\begin{document}/' main.tex
pdflatex -synctex=1 -interaction=batchmode main.tex >/dev/null
echo "\\includeonly{c}:"; first | head -3
sed -i 's/\\includeonly{c}//' main.tex; rm -f main.aux a.aux b.aux c.aux
python -m chapmk check main.tex >c1.out 2>&1
sed -i 's/Text c\./Txet c./' c.tex
python -m chapmk check main.tex >c2.out 2>&1; grep -E "PASS|FAIL" c2.out
python - <<'PY'
from pathlib import Path
from chapmk.synctex import parse
a, b = parse(Path(".chapmk/main/check/main.synctex.gz")), parse(Path("main.synctex.gz"))
print("records per page, reference:", [len(a.sheets[p]) for p in sorted(a.sheets)])
print("records per page, chapmk:   ", [len(b.sheets[p]) for p in sorted(b.sheets)])
PY
