#!/usr/bin/env bash
# Smoke test of the MiKTeX dev image (Dockerfile.miktex): the tools chapmk needs work on the
# test corpora. Run inside the image with the repository at /work:
#   docker run --rm -v "$PWD":/work:ro chapmk-miktex bash /work/tests/miktex-smoke.sh
# Exit code 1 if a required check fails. Known differences to TeX Live are reported as "note"
# (inputs for spike S11), not as failures.
set -u
fail=0
ok() { echo "OK    $*"; }
bad() { echo "FAIL  $*"; fail=1; }
note() { echo "note  $*"; }

w=$(mktemp -d)
cp -r /work/tests/corpus/thesis /work/tests/corpus/hgb /work/tests/corpus/minimal/S1-format "$w"/
cat > "$w/latexmkrc" <<'R'
add_cus_dep('nlo', 'nls', 0, 'nlo2nls');
sub nlo2nls { return system("makeindex -s nomencl.ist -o '$_[0].nls' '$_[0].nlo'"); }
R
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1

pdflatex --version | head -1
for f in "$w"/thesis/fig/*.tex; do
  (cd "$w/thesis/fig" && pdflatex -interaction=nonstopmode -halt-on-error "$(basename "$f")" >/dev/null 2>&1) \
    || bad "figure $(basename "$f")"
done
mkdir -p "$w/thesis/fig_tmp"
latexmk_pdf() {
  (cd "$w/$1" && latexmk -pdf -shell-escape -synctex=1 -interaction=nonstopmode -halt-on-error \
    -r "$w/latexmkrc" main.tex >latexmk.out 2>&1)
}
if latexmk_pdf thesis; then ok "latexmk thesis ($(pdfinfo "$w/thesis/main.pdf" | grep Pages | tr -s ' '))"
else bad "latexmk thesis"; grep -m3 -A3 "^!" "$w/thesis/main.log"; fi
[ -s "$w/thesis/main.bbl" ] && ok "biber (.bbl)" || bad "biber (.bbl)"
[ -s "$w/thesis/main.nls" ] && ok "makeindex nomencl (.nls)" || bad "makeindex (.nls)"
line=$(grep -n "tableofcontents" "$w/thesis/main.tex" | head -1 | cut -d: -f1)  # a body line with records
if (cd "$w/thesis" && synctex view -i "$line":1:"$w/thesis/main.tex" -o main.pdf | grep -q "^Page:"); then
  ok "synctex view (absolute path)"; else bad "synctex view (absolute path)"; fi
if (cd "$w/thesis" && synctex view -i "$line":1:main.tex -o main.pdf | grep -q "^Page:"); then
  ok "synctex view (relative path)"
else note "synctex view with a relative path finds nothing: MiKTeX writes Input paths without /./"; fi
if latexmk_pdf hgb; then ok "latexmk hgb"
else note "hgb corpus fails ($(grep -m1 -A1 '^!' "$w/hgb/main.log" | tr '\n' ' ')): hgbthesis version"; fi
(cd "$w/S1-format" && pdflatex -ini -interaction=nonstopmode -halt-on-error -jobname=pre \
  "&pdflatex" mylatexformat.ltx main.tex >fmt.out 2>&1) && [ -s "$w/S1-format/pre.fmt" ] \
  && ok "mylatexformat format build" || bad "mylatexformat format build"
exit $fail
