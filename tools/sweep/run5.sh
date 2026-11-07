#!/bin/bash
# wait for the case run, free the clones of sample 3, clone sample 5, sweep (variant, pre-filter, latexmk)
S=$SCRATCH
while docker ps --format "{{.Names}}" | grep -qx cases; do sleep 20; done
mkdir -p $S/sweep/gh5 && cd $S/sweep/gh5
python3 -c "import json; [print(e['id'][3:]) for e in json.load(open('$S/sweep/manifest5.json'))]" | while read r; do
  d=${r//\//__}; [ -d $d ] || timeout 300 git clone -q --depth 1 https://github.com/$r.git $d >/dev/null 2>&1 || echo "clone failed: $r"
done
docker run --rm --name sweep5 -v $S/sweep:/sweep -v $S/src-main5/src:/src:ro -e PYTHONPATH=/src -e SOURCE_DATE_EPOCH=1700000000 --user root chapmk-dev python3 /sweep/sweep.py --variant --prefilter --latexmk /sweep/manifest5.json /sweep/results5.jsonl
