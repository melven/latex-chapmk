#!/bin/bash
# S13: pdfTeX state a format does not keep. Run in the dev container from the repository root:
#   bash tests/corpus/minimal/S13-format-state/run.sh
# Each case is copied to a temporary directory and built with chapmk build --check.
#   cmap              \immediate\pdfobj (cmap's ToUnicode CMaps) before the split: FAIL (math text)
#   colorstack        \pdfcolorstackinit before the split: TeX error "Unknown color stack number 1"
#   colorstack-driver xcolor with TeX Live 2026's driver (stack 0 only): PASS
#   colorleak-textpos  a colour set in a textpos block on the title page reaches the next page
#                     in a plain build, not with the format (xcolor's push on the main vertical
#                     list is not dumped): PASS since the replay, FAIL (page 2) before;
#                     without chapmk: colorleak-textpos/compare.sh (TeX Live and MiKTeX alike)
#   catalog-info      \pdfcatalog, \pdfinfo before the split: PASS, but /PageMode and /Keywords
#                     are missing in the incremental PDF (printed below; check does not compare them)
set -u
here=$(cd "$(dirname "$0")" && pwd)
for case in cmap colorstack colorstack-driver catalog-info colorleak-textpos; do
  tmp=$(mktemp -d)
  cp -r "$here/$case" "$tmp/src"
  echo "== $case"
  (cd "$tmp/src" && SOURCE_DATE_EPOCH=1700000000 python -m chapmk build --check main.tex 2>&1 \
     | grep -E "^PASS|^FAIL|DIFFERS|error" | cut -c1-160)
  grep -h "chapmk-pdf-objects\|dangling" "$tmp/src/.chapmk/main/fmt/pre.log"
done
python - "$tmp/src" <<'PY'
import sys, pikepdf
for name, path in (("incremental", "main.pdf"), ("--full", ".chapmk/main/check/main.pdf")):
    with pikepdf.open(f"{sys.argv[1]}/{path}") as pdf:
        print(name, "PageMode:", pdf.Root.get("/PageMode"), "Keywords:", pdf.docinfo.get("/Keywords"))
PY
