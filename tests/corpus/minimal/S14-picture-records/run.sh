#!/usr/bin/env bash
# S14: builds the case with chapmk (cold, then an edit of u2 so that u1's aux stays canonical)
# and reports duplicate label records. Run in the dev image from the repository root:
#   bash tests/corpus/minimal/S14-picture-records/run.sh
set -u
w=$(mktemp -d)
cp tests/corpus/minimal/S14-picture-records/*.tex "$w"/
cd "$w"
export SOURCE_DATE_EPOCH=1700000000
chapmk build main.tex >build1.out 2>&1; echo "cold build: exit $?"
grep -c "multiply defined" main.log | sed 's/^/  multiply defined in main.log: /'
grep -h "pgfid\|pic:node" .chapmk/main/canon/u1.aux | sed 's/^/  canon u1.aux: /'
echo "Two, edited." >> u2.tex
chapmk build main.tex >build2.out 2>&1; echo "incremental build: exit $?"
grep -h "multiply defined" main.log | sed 's/^/  /'
chapmk build main.tex --full --out-dir full >build3.out 2>&1; echo "full build: exit $?"
grep -c "multiply defined" full/main.log | sed 's/^/  multiply defined in full log: /'
