#!/bin/bash
# clone the repositories of manifest4.json, then sweep them (variant + latexmk reference)
S=$SCRATCH
mkdir -p $S/sweep/gh4 && cd $S/sweep/gh4
python3 -c "import json; [print(e['id'][3:]) for e in json.load(open('$S/sweep/manifest4.json'))]" | while read r; do
  d=${r//\//__}; [ -d $d ] || timeout 300 git clone -q --depth 1 https://github.com/$r.git $d >/dev/null 2>&1 || echo "clone failed: $r"
done
# code: src-newest (prepared before)
docker run --rm --name sweep4 -v $S/sweep:/sweep -v $S/src-newest/src:/src:ro -e PYTHONPATH=/src -e SOURCE_DATE_EPOCH=1700000000 --user root chapmk-dev python3 /sweep/sweep.py --variant --prefilter --latexmk /sweep/manifest4.json /sweep/results4.jsonl
