#!/bin/bash
# re-run all correctness cases (cold --check, typo, latexmk vs --full) on one code snapshot
S=$SCRATCH
cd $S/sweep
python3 -c "import json; [print(m, *ids) for m, ids in json.load(open('rerun-ids.json')).items()]" | while read m ids; do
  docker run --rm --name rerun -v $S/sweep:/sweep -v $S/src-main7/src:/src:ro -e PYTHONPATH=/src -e SOURCE_DATE_EPOCH=1700000000 --user root chapmk-dev python3 /sweep/sweep.py --variant --latexmk /sweep/$m /sweep/rerun.jsonl $ids
done
