#!/usr/bin/env bash
# Spike S2: -output-directory read order, stale files in the source dir, shadow tree
# (docs/spikes/S2.md). Usage (dev container, cwd = this directory): ./run.sh OUTDIR
set -u
HERE=$(pwd); OUT=$(realpath -m "${1:?outdir}"); rm -rf "$OUT"; mkdir -p "$OUT"
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000
FLAGS=(-interaction=nonstopmode -halt-on-error -file-line-error -synctex=1 -recorder)

pass() {  # CWD OUTDIR -> one pdflatex pass
  (cd "$1" && pdflatex "${FLAGS[@]}" -output-directory="$2" -jobname=main main.tex >"$2/pass.out" 2>&1) \
    || echo "  FAIL: $(grep -m1 -E '^!|^[^ ]*:[0-9]+: ' "$2/main.log" 2>/dev/null || tail -2 "$2/pass.out")"
}
full() {  # CWD OUTDIR -> pdflatex, biber, pdflatex x2
  pass "$1" "$2"; (cd "$1" && biber --output-directory "$2" main >"$2/biber.out" 2>&1) || echo "  biber FAIL"
  pass "$1" "$2"; pass "$1" "$2"
}
stale() { pdftotext "$1/main.pdf" - 2>/dev/null | grep -o 'STALE[A-Z]*' | sort -u | tr '\n' ' '; }

# "User source dir": a copy of this directory plus a generated figure fig/a.pdf
SRC="$OUT/src"; mkdir -p "$SRC/fig" "$OUT/tmp"
cp -r "$HERE"/main.tex "$HERE"/refs.bib "$HERE"/chap "$SRC"/
(cd "$OUT/tmp" && pdflatex -interaction=batchmode "$HERE/fig.tex" >/dev/null && mv fig.pdf "$SRC/fig/a.pdf")

echo "== reference: clean source copy, fresh output dir"
cp -r "$SRC" "$OUT/clean"; mkdir -p "$OUT/o-ref/chap"; full "$OUT/clean" "$OUT/o-ref"
pdftotext -layout "$OUT/o-ref/main.pdf" "$OUT/o-ref/main.txt"

# Plant stale build files in the source dir (as left over by a manual build)
printf '%s\n' '\relax' '\@input{chap/unit.aux}' '\newlabel{sec:main}{{STALEMAINAUX}{1}{}{}{}}' >"$SRC/main.aux"
printf '%s\n' '\relax' '\newlabel{sec:unit}{{STALEUNITAUX}{1}{}{}{}}' >"$SRC/chap/unit.aux"
printf '%s\n' '\contentsline {section}{\numberline {9}STALETOC}{1}{}%' >"$SRC/main.toc"

echo "== plain source dir with stale files, fresh output dir, 1 pass"
mkdir -p "$OUT/o-p1/chap"; pass "$SRC" "$OUT/o-p1"; echo "  stale markers in PDF: $(stale "$OUT/o-p1")"
grep -E "^(INPUT|OUTPUT) .*(main\.(aux|toc)|unit\.aux)" "$OUT/o-p1/main.fls" | sort -u | sed 's/^/  /'

echo "== plain source dir with stale files, full build into the same output dir"
mkdir -p "$OUT/o-p2/chap"; full "$SRC" "$OUT/o-p2"; echo "  stale markers in PDF: $(stale "$OUT/o-p2")"
grep -E "^INPUT .*(main\.(aux|toc)|unit\.aux)" "$OUT/o-p2/main.fls" | sort -u | sed 's/^/  /'

echo "== shadow tree (symlinks, build outputs excluded), fresh output dir WITHOUT chap/"
SH="$OUT/shadow"; cp -as "$SRC" "$SH"
find "$SH" -type l \( \( -name 'main.*' ! -name main.tex \) -o -path "$SH/chap/unit.aux" \) -delete
find "$SH" -maxdepth 2 | sed "s|$OUT/||" | sort | tr '\n' ' '; echo
mkdir -p "$OUT/o-nochap"; pass "$SH" "$OUT/o-nochap"

echo "== shadow tree, fresh output dir with chap/"
mkdir -p "$OUT/o-sh/chap"; full "$SH" "$OUT/o-sh"; echo "  stale markers in PDF: $(stale "$OUT/o-sh")"
pdftotext -layout "$OUT/o-sh/main.pdf" "$OUT/o-sh/main.txt"
for d in o-ref o-sh; do rm -f "$OUT/$d"/pg-*; pdftoppm -r 150 "$OUT/$d/main.pdf" "$OUT/$d/pg"; done
n=0; bad=0; for f in "$OUT"/o-ref/pg-*; do n=$((n+1)); cmp -s "$f" "$OUT/o-sh/$(basename "$f")" || bad=$((bad+1)); done
echo "  raster vs reference: $((n-bad))/$n identical; text: $(cmp -s "$OUT/o-ref/main.txt" "$OUT/o-sh/main.txt" && echo identical || echo DIFFERS)"
echo "  figure: $(grep -o '<[^>]*a\.pdf>' "$OUT/o-sh/main.log" | head -1)"
echo "  biber data source: $(grep -o "Found BibTeX data source '[^']*'" "$OUT/o-sh/main.blg")"
for d in o-ref o-sh; do
  echo "  [$d] SyncTeX inputs: $(zcat "$OUT/$d/main.synctex.gz" | grep '^Input:' | cut -d: -f3- | tr '\n' ' ')"
  echo "  [$d] view chap/unit.tex:2 -> $(cd "$OUT/${d/o-ref/clean}"; [ "$d" = o-sh ] && cd "$SH"; \
     synctex view -i 2:1:chap/unit.tex -o "$OUT/$d/main.pdf" | awk '/^Page:|^h:|^v:/' | tr '\n' ' ')"
done
p=$(cd "$SH" && synctex view -i 2:1:chap/unit.tex -o "$OUT/o-sh/main.pdf" | awk -F: '/^Page:/{p=$2}/^x:/{x=$2}/^y:/{print p, x, $2; exit}')
set -- $p
echo "  [o-sh] edit page $1 ($2,$3) -> $(cd "$SH" && synctex edit -o "$1:$2:$3:$OUT/o-sh/main.pdf" | awk -F: '/^Input:|^Line:/{printf "%s ", $0}')"
