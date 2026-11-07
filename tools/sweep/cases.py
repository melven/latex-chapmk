"""Correctness cases of the sweeps as Markdown: python3 cases.py SCRATCH > correctness-cases.md

A case: a cold incremental build that fails --check (§3.3 against chapmk's full build), or
chapmk's full build differing from latexmk. Per case: repository at the pinned commit, main
file, robustness variant, first differences.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

scratch = Path(sys.argv[1])
sweep = scratch / "sweep"
runs = [("manifest3.json", "cases3.jsonl"), ("manifest4.json", "cases4.jsonl")]
# latexmk comparisons re-run with all DIFFERS lines (lm4.jsonl) and notes from a first look
relm = {json.loads(ln)["id"]: json.loads(ln) for ln in open(sweep / "lm4.jsonl")} \
    if (sweep / "lm4.jsonl").is_file() else {}
NOTES = {
    "gh/albertopasqualetto/Master-thesis": "latexmk used the repository's `.latexmkrc` (LuaLaTeX):"
    " harness error, `sweep.py` now passes `-norc`; chapmk's format build fails"
    " (`docs/glossary.tex:5`), full mode, `--check` passes.",
    "gh/bryancrisso/partiiproject": "latexmk's List of Figures shows the unresolved key `[ddg]`"
    " of a citation in a caption, chapmk's `[1]`; 79 vs 81 pages. Possibly latexmk stopping"
    " one run early; not checked.",
}


def commit(root: str) -> str:
    local = sweep / root.removeprefix("/sweep/")
    r = subprocess.run(["git", "-C", str(local), "rev-parse", "HEAD"], capture_output=True,
                       text=True)
    return r.stdout.strip()[:12] or "?"


def diffs(messages: list[str]) -> list[str]:
    out = [re.sub(r"/sweep/work/tmp\w+/doc/", "", m.strip()) for m in messages if "DIFFER" in m]
    return [d[:200] for d in out[:3]]


print("# Correctness cases (corpus sweeps)\n")
print("Re-run on `main` `fc71b5b` (after PR 66). ", end="")
print("Cold incremental builds that fail `--check` (§3.3 against chapmk's own full build) and")
print("full builds that differ from latexmk. Documents are public GitHub repositories at the")
print("pinned commit; `variant`: the sweep's robustness changes (see `sweep.py`: fontspec setup")
print("commented out, `bookmark` added, BibTeX replaced by biblatex). Reproduce with")
print("`sweep.py --variant --latexmk <manifest> <out> <id>`.\n")
for manifest, results in runs:
    if not (sweep / results).is_file():
        continue
    man = {e["id"]: e for e in json.load(open(sweep / manifest))}
    print(f"## From `{manifest}`\n")
    for line in open(sweep / results):
        r = json.loads(line)
        e = man[r["id"]]
        repo = r["id"].removeprefix("gh/")
        if r["id"] in relm:
            r["reference"] = relm[r["id"]].get("reference")
        cold, typo, ref = r.get("cold") or {}, r.get("typo") or {}, r.get("reference") or {}
        fixed = cold.get("check") == "PASS" and typo.get("check", "PASS") == "PASS" \
            and ref.get("vs_latexmk") == "PASS"
        print(f"### [{repo}](https://github.com/{repo}) `{commit(e['root'])}`"
              + (" (passes on `main` `fc71b5b`)" if fixed else "") + "\n")
        print(f"- main file: `{e['main']}`, class `{e.get('class')}`, variant: "
              f"{', '.join(r.get('variant') or []) or 'none'}")
        state = f"{cold.get('mode')} / {cold.get('check')}"
        print(f"- cold build: {state}" + (f" (reason: {cold.get('reason')})" if cold.get("reason") else ""))
        for d in diffs(cold.get("messages", [])):
            print(f"  - `{d}`")
        if typo:
            print(f"- typo build: {typo.get('mode')} / {typo.get('check')}")
            for d in diffs(typo.get("messages", [])):
                print(f"  - `{d}`")
        if ref.get("vs_latexmk"):
            print(f"- full build vs latexmk: {ref['vs_latexmk']}")
            for d in [x.strip() for x in ref.get("vs_latexmk_summary", []) if "DIFF" in x][:3]:
                print(f"  - `{d[:200]}`")
        if r["id"] in NOTES:
            print(f"- note: {NOTES[r['id']]}")
        print()
print("## Earlier cases\n")
print("- [rimrim/thesis](https://github.com/rimrim/thesis) (`manifest2.json`): full build vs")
print("  latexmk differs in one SyncTeX record (page 50, a `description` item box in")
print("  `chapter2.tex:915` shifted by 24379 sp); pixels and text identical. Open.")
print("- Fixed: babel-spanish roman page labels (PR 64), `\\include{./x}` and `\\include{x.tex}`")
print("  (PR 63), page labels without hyperref (PR 65), `.bcf` self-check numbering and an")
print("  `\\include` in a class macro (PR 66).")
