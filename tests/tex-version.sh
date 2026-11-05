#!/usr/bin/env bash
# One line describing the TeX installation in use: distribution banner, LaTeX kernel version
# and the date of its package state (CI job summaries, .github/workflows/texlive-*.yml, miktex-current.yml).
set -e
banner=$(pdflatex --version | head -1)
dir=$(mktemp -d)
cd "$dir"
printf '%s\n' '\typeout{KERNEL=\fmtversion\space patch level \csname patch@level\endcsname}\stop' > k.tex
pdflatex -interaction=batchmode k.tex >/dev/null 2>&1 || true
kernel=$(sed -n 's/^KERNEL=//p' k.log | head -1)
db="$(kpsewhich -var-value TEXMFROOT 2>/dev/null || true)/tlpkg/texlive.tlpdb"
if [ -f "$db" ]; then
  packages="packages as of $(date -u -r "$db" +%F)"   # TeX Live: last tlmgr update of the image
else
  packages="packages as of $(date -u +%F)"            # MiKTeX: installed from the mirror today
fi
echo "$banner; LaTeX $kernel; $packages"
