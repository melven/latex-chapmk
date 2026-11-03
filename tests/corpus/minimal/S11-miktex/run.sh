#!/usr/bin/env bash
# Spike S11: MiKTeX (docs/spikes/S11.md). Runs inside the MiKTeX image (Dockerfile.miktex):
#   docker run --rm -v "$PWD":/work:ro chapmk-miktex bash /work/tests/corpus/minimal/S11-miktex/run.sh OUT
# Prints one result block per question; OUT keeps the files.
set -u
OUT=$(realpath -m "${1:-/tmp/s11}"); rm -rf "$OUT"; mkdir -p "$OUT"
HERE=$(dirname "$(readlink -f "$0")")
export SOURCE_DATE_EPOCH=1700000000 FORCE_SOURCE_DATE=1 max_print_line=10000
FLAGS=(-interaction=nonstopmode -halt-on-error -file-line-error -synctex=1 -recorder)
q() { echo; echo "== $*"; }

q "1 tools and versions"
for t in pdflatex biber makeindex synctex kpsewhich initexmf mpm latexmk; do
  printf '  %-10s %s\n' "$t" "$(command -v $t)"; done
pdflatex --version | head -1 | sed 's/^/  /'
biber --version | head -1 | sed 's/^/  /'
for f in mylatexformat.ltx nomencl.sty biblatex.sty bookmark.sty hyperref.sty; do
  printf '  %-18s %s\n' "$f" "$(kpsewhich $f)"; done
echo "  LaTeX kernel: $(grep -m1 -o '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "$(kpsewhich latex.ltx)")"
echo "  AutoInstall (user/admin): $(initexmf --show-config-value '[MPM]AutoInstall' 2>/dev/null)/$(initexmf --admin --show-config-value '[MPM]AutoInstall' 2>/dev/null)"

q "2 TEXINPUTS: a directory prepended by the driver (chapmk's .sty files, the run main)"
mkdir -p "$OUT/inputs/dir" "$OUT/inputs/cwd"
printf '\\ProvidesPackage{s11probe}\\def\\probe{FOUND-VIA-TEXINPUTS}\n' > "$OUT/inputs/dir/s11probe.sty"
printf '\\documentclass{article}\\usepackage{s11probe}\\begin{document}\\probe\\end{document}\n' > "$OUT/inputs/dir/s11run.tex"
(cd "$OUT/inputs/cwd" && TEXINPUTS="$OUT/inputs/dir:" pdflatex "${FLAGS[@]}" -output-directory="$OUT/inputs/cwd" s11run.tex >out.txt 2>&1) \
  && echo "  ok: $(pdftotext "$OUT/inputs/cwd/s11run.pdf" - | head -1)" || echo "  FAIL: $(grep -m1 -E '^!|not found' "$OUT/inputs/cwd/out.txt" "$OUT/inputs/cwd/s11run.log" 2>/dev/null)"

q "3 format build (texdist.format_build argv) and use via -fmt=NAME + TEXFORMATS"
mkdir -p "$OUT/fmt/f" "$OUT/fmt/run"
cp "$HERE/../S1-format/main.tex" "$HERE/../S1-format/thesis.bib" "$OUT/fmt/"
B=$(grep -n '\\begin{document}' "$OUT/fmt/main.tex" | head -1 | cut -d: -f1)
S=$(grep -n 'hyperref' "$OUT/fmt/main.tex" | head -1 | cut -d: -f1)
head -n $((S-1)) "$OUT/fmt/main.tex" > "$OUT/fmt/f/pre.tex"; echo '\endofdump' >> "$OUT/fmt/f/pre.tex"
(cd "$OUT/fmt" && pdflatex -ini -interaction=nonstopmode -halt-on-error -file-line-error -recorder -jobname=pre \
   -output-directory="$OUT/fmt/f" "&pdflatex" mylatexformat.ltx "$OUT/fmt/f/pre.tex" >"$OUT/fmt/f/build.out" 2>&1) \
  && echo "  format: $(ls -s "$OUT/fmt/f/pre.fmt" 2>/dev/null)" || echo "  FAIL format: $(grep -m1 -E '^!' "$OUT/fmt/f/pre.log")"
awk -v s=$S '{ if (NR < s) print ""; else if (NR == s) print "\\csname endofdump\\endcsname" $0; else print }' \
  "$OUT/fmt/main.tex" > "$OUT/fmt/run/s11run.tex"
for variant in texformats undump; do
  d="$OUT/fmt/$variant"; mkdir -p "$d"
  if [ $variant = texformats ]; then args=(-fmt=pre); env=(TEXFORMATS="$OUT/fmt/f:"); else args=("--undump=$OUT/fmt/f/pre.fmt"); env=(); fi
  (cd "$OUT/fmt" && env "${env[@]}" TEXINPUTS="$OUT/fmt/run:" pdflatex "${args[@]}" "${FLAGS[@]}" -output-directory="$d" -jobname=main s11run.tex >"$d/out.txt" 2>&1) \
    && echo "  $variant: ok, $(grep -c '' "$d/main.fls") .fls lines, format in .fls: $(grep -c 'pre.fmt' "$d/main.fls")" \
    || echo "  $variant: FAIL $(grep -m1 -E '^!|fmt|format' "$d/out.txt")"
done
echo "  log banner: $(grep -m1 -o 'format=[^)]*\|preloaded format=[^)]*' "$OUT/fmt/texformats/main.log")"

q "4 -recorder .fls (path forms parsed by fullbuild.read_inputs)"
head -3 "$OUT/fmt/undump/main.fls" | sed 's/^/  /'
grep -E "^(INPUT|OUTPUT) .*(main\.(aux|toc|pdf)|s11run\.tex|pre\.fmt)" "$OUT/fmt/undump/main.fls" | sort -u | sed 's/^/  /'

q "5 SOURCE_DATE_EPOCH / FORCE_SOURCE_DATE"
mkdir -p "$OUT/date"; printf '\\documentclass{article}\\begin{document}\\today\\end{document}\n' > "$OUT/date/d.tex"
(cd "$OUT/date" && pdflatex -interaction=nonstopmode d.tex >/dev/null 2>&1)
echo "  \\today with epoch 1700000000 (2023-11-14): $(pdftotext "$OUT/date/d.pdf" - | head -1)"
echo "  PDF dates: $(pdfinfo -isodates "$OUT/date/d.pdf" | grep -E 'CreationDate|ModDate' | tr -s ' ' | tr '\n' ' ')"
cp "$OUT/date/d.pdf" "$OUT/date/d1.pdf"; sleep 2; (cd "$OUT/date" && pdflatex -interaction=nonstopmode d.tex >/dev/null 2>&1)
cmp -s "$OUT/date/d.pdf" "$OUT/date/d1.pdf" && echo "  two runs: byte-identical" || echo "  two runs: DIFFER"

q "6 max_print_line (picture records rely on unbroken log lines up to 10000)"
mkdir -p "$OUT/mpl"; printf '\\typeout{LONG%s}\\documentclass{article}\\begin{document}x\\end{document}\n' "$(printf 'x%.0s' $(seq 1 300))" > "$OUT/mpl/m.tex"
(cd "$OUT/mpl" && pdflatex -interaction=nonstopmode m.tex >/dev/null 2>&1)
echo "  env max_print_line=10000: longest LONG line $(grep -A3 '^LONG' "$OUT/mpl/m.log" | head -1 | wc -c) chars (304 = unbroken)"
(cd "$OUT/mpl" && pdflatex --max-print-line=10000 -interaction=nonstopmode m.tex >/dev/null 2>&1)
echo "  --max-print-line=10000: $(grep '^LONG' "$OUT/mpl/m.log" | head -1 | wc -c) chars"

q "7 SyncTeX Input paths: cwd = symlinked shadow tree, relative input (S2/S10 rely on <cwd>/./<rel>)"
mkdir -p "$OUT/sync/src/chap" "$OUT/sync/o/chap"
printf '\\documentclass{article}\\begin{document}\nMain text.\n\\include{chap/u}\n\\end{document}\n' > "$OUT/sync/src/main.tex"
printf 'Unit line one.\n\nUnit line three.\n' > "$OUT/sync/src/chap/u.tex"
cp -as "$OUT/sync/src" "$OUT/sync/shadow"
(cd "$OUT/sync/shadow" && pdflatex "${FLAGS[@]}" -output-directory="$OUT/sync/o" main.tex >/dev/null 2>&1)
zcat "$OUT/sync/o/main.synctex.gz" | grep '^Input:' | grep -v miktex-texmf | sed 's/^/  /'
for name in chap/u.tex ./chap/u.tex "$OUT/sync/shadow/chap/u.tex"; do
  echo "  view -i 3:1:$name -> $(cd "$OUT/sync/shadow" && synctex view -i "3:1:$name" -o "$OUT/sync/o/main.pdf" 2>&1 | grep -m1 -E '^Page:|Warning')"
done

q "8 -output-directory read order and shadow tree: S2 reproducer under MiKTeX"
(cd "$HERE/../S2-paths" && bash ./run.sh "$OUT/s2" 2>&1 | sed 's/^/  /')

q "9 mylatexformat runtime skip and identity with a plain build (S1 under MiKTeX, --undump)"
# (S1's own run.sh finds the format via TEXFORMATS, which MiKTeX ignores: see 3)
full() {  # DIR TEX [args]: pdflatex, biber, pdflatex x2 in $OUT/fmt
  local d=$1 tex=$2; shift 2; mkdir -p "$d"
  for pass in 1 2 3; do
    (cd "$OUT/fmt" && TEXINPUTS="$OUT/fmt/run:" pdflatex "$@" "${FLAGS[@]}" -output-directory="$d" -jobname=main "$tex" >"$d/p$pass.out" 2>&1) \
      || { echo "  FAIL $d pass $pass: $(grep -m1 -E '^!|^[^ ]*:[0-9]+: ' "$d/main.log")"; return 1; }
    [ $pass = 1 ] && (cd "$OUT/fmt" && biber --output-directory "$d" main >"$d/biber.out" 2>&1)
  done; return 0
}
full "$OUT/fmt/ref" main.tex && full "$OUT/fmt/use" s11run.tex "--undump=$OUT/fmt/f/pre.fmt" && {
  for d in ref use; do pdftoppm -r 150 "$OUT/fmt/$d/main.pdf" "$OUT/fmt/$d/pg"; pdftotext -layout "$OUT/fmt/$d/main.pdf" "$OUT/fmt/$d/main.txt"; done
  n=0; bad=0; for f in "$OUT"/fmt/ref/pg-*; do n=$((n+1)); cmp -s "$f" "$OUT/fmt/use/$(basename "$f")" || bad=$((bad+1)); done
  echo "  raster: $((n-bad))/$n identical; text: $(cmp -s "$OUT/fmt/ref/main.txt" "$OUT/fmt/use/main.txt" && echo identical || echo DIFFERS)"
  for l in $((B+6)) $((B+10)) $((B+14)); do
    r=$(synctex view -i "$l:1:$OUT/fmt/main.tex" -o "$OUT/fmt/ref/main.pdf" | awk '/^Page:|^h:|^v:/' | tr '\n' ' ')
    u=$(synctex view -i "$l:1:$OUT/fmt/run/s11run.tex" -o "$OUT/fmt/use/main.pdf" | awk '/^Page:|^h:|^v:/' | tr '\n' ' ')
    echo "  synctex line $l: ref [$r] format [$u] $([ "$r" = "$u" ] && echo same || echo DIFFERENT)"
  done; }
