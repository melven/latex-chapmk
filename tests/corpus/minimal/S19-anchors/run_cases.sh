cd "$1"
for d in */; do d=${d%/}; cd $d
  r1=$(python -m chapmk build main.tex -j 4 --check --keep-runs 2>&1 | grep -cE "^PASS")
  sed -i 's/^Text a\./Text a typo./' a.tex
  r2=$(python -m chapmk build main.tex -j 4 --check --keep-runs 2>&1 | grep -cE "^PASS")
  recs=$(cat .chapmk/main/runs/*/*.frec | grep -E "^[RH] " | sort | uniq -c | tr '\n' ';')
  echo "$d cold-pass=$r1 typo-pass=$r2 | $recs"
  cd ..
done
