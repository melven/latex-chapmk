#!/bin/bash
# clone sample 6, sweep (variant, pre-filter, latexmk)
S=$SCRATCH
mkdir -p $S/sweep/gh6 && cd $S/sweep/gh6
python3 -c "import json; [print(e['id'][3:]) for e in json.load(open('$S/sweep/manifest6.json'))]" | while read r; do
  d=${r//\//__}; [ -d $d ] || timeout 300 git clone --filter=blob:limit=20m -q --depth 1 https://github.com/$r.git $d >/dev/null 2>&1 || echo "clone failed: $r"
  [ -d $d ] && [ $(du -sm $d | cut -f1) -gt 300 ] && rm -rf $d && echo "too large: $r"
done
docker run --rm --name sweep6 -v $S/sweep:/sweep -v $S/src-main6/src:/src:ro -e PYTHONPATH=/src -e SOURCE_DATE_EPOCH=1700000000 --user root chapmk-dev python3 /sweep/sweep.py --variant --prefilter --latexmk /sweep/manifest6.json /sweep/results6.jsonl
