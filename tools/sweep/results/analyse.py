"""Per failing case: fresh cold incremental build, full comparison against the --check reference."""
import json, glob, re, subprocess, difflib, shutil, sys
from pathlib import Path
from chapmk.check import compare_pdfs
out = open('/sweep/analysis.jsonl', 'a')
done = {json.loads(l)['id'] for l in open('/sweep/analysis.jsonl')} if Path('/sweep/analysis.jsonl').stat().st_size else set()
man = {}
for m in glob.glob('/sweep/manifest*.json'):
    for e in json.load(open(m)): man[e['id']] = e
for l in open('/sweep/rerun.jsonl'):
    r = json.loads(l); w = r.get('workdir')
    c = r.get('cold') or {}
    if not w or c.get('check') != 'FAIL' or r['id'] in done:
        continue
    main = Path(w) / 'doc' / man[r['id']]['main']
    job = main.stem
    bd = main.parent / '.chapmk' / job
    ref = Path(w) / 'ref.pdf'
    if not ref.is_file():
        shutil.copy(bd / 'check' / f'{job}.pdf', ref)
    shutil.rmtree(bd)
    p = subprocess.run(['python3', '-m', 'chapmk', 'build', main.name, '-j', '4', '--report', str(Path(w) / 'cold.json')],
                       cwd=main.parent, capture_output=True, text=True)
    got = main.parent / f'{job}.pdf'
    rep = compare_pdfs(ref, got)
    diffs = [d for d in rep.summary().splitlines() if 'DIFFERS' in d]
    pages = sorted({int(m.group(1)) for d in diffs if 'text pages' in d for m in [re.search(r'#(\d+)', d)] if m})
    snippets = []
    if pages:
        t = [subprocess.run(['pdftotext', '-layout', str(x), '-'], capture_output=True, text=True).stdout.split('\f') for x in (ref, got)]
        pg = pages[0]
        d = [x.rstrip()[:160] for x in difflib.unified_diff(t[0][pg].splitlines(), t[1][pg].splitlines(), lineterm='', n=0)
             if x[:1] in '+-' and x[:3] not in ('---', '+++')]
        snippets = d[:8]
    res = {'id': r['id'], 'rc': p.returncode, 'diffs': [x.strip()[:250] for x in diffs], 'snippet': snippets,
           'report': json.load(open(Path(w) / 'cold.json')) if (Path(w) / 'cold.json').is_file() else None}
    out.write(json.dumps(res) + '\n'); out.flush()
    print(r['id'], len(diffs), flush=True)
