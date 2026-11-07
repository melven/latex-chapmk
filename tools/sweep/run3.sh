#!/bin/bash
# clone the repositories of manifest3.json, then sweep them (variant + latexmk reference)
S=$SCRATCH
mkdir -p $S/sweep/gh3 && cd $S/sweep/gh3
python3 -c "import json; [print(e['id'][3:]) for e in json.load(open('$S/sweep/manifest3.json'))]" | while read r; do
  d=${r//\//__}; [ -d $d ] || timeout 300 git clone -q --depth 1 https://github.com/$r.git $d >/dev/null 2>&1 || echo "clone failed: $r"
done
rm -rf $S/src-main && mkdir -p $S/src-main && git -C /home/user/latex-chapmk archive origin/main src | tar -x -C $S/src-main
docker run --rm --name sweep3 -v $S/sweep:/sweep -v $S/src-main/src:/src:ro -e PYTHONPATH=/src -e SOURCE_DATE_EPOCH=1700000000 --user root chapmk-dev python3 /sweep/sweep.py --variant --prefilter --latexmk /sweep/manifest3.json /sweep/results3.jsonl
