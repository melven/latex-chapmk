"""Markdown table of a sweep: python3 table.py manifest.json results.jsonl"""

import json
import re
import sys


def status(r: dict) -> tuple[str, str]:
    cold, typo, full = r.get("cold", {}), r.get("typo"), r.get("full")
    err = next((m for m in cold.get("messages", []) if "error" in m.lower()), "")
    err = re.sub(r"/tmp/tmp\w+/doc/", "", err).replace("chapmk: error: ", "")
    if cold.get("rc") == -1:
        return "timeout", "cold build > 30 min"
    if cold.get("rc") == 2:
        return "chapmk refuses", err[:110]
    if cold.get("rc") != 0:
        msgs = (full or cold).get("messages", [])
        tex = next((m for m in msgs if re.match(r"^(!|\S+:\d+: )", m)), "")
        if full and full.get("rc") != 0:
            return "doc fails", re.sub(r"/tmp/tmp\w+/doc/", "", tex or err)[:110]
        return "FAIL cold", (tex or err)[:110]
    if cold.get("check") != "PASS":
        return "FAIL §3.3 cold", "; ".join(cold.get("messages", [])[:2])[:110]
    notes = []
    if cold.get("mode") == "full":
        notes.append(f"full: {cold.get('reason')}")
    if typo is None:
        return "ok (cold only)", "; ".join(notes + ["no plain text line for a typo"])
    if typo.get("rc") != 0:
        terr = next((m for m in typo.get("messages", []) if "rror" in m), "")
        return "FAIL typo", re.sub(r"/tmp/tmp\w+/doc/", "", terr)[:110]
    if typo.get("check") != "PASS":
        return "FAIL §3.3 typo", "; ".join(typo.get("messages", [])[:2])[:110]
    if typo.get("mode") != "incremental":
        notes.append(f"typo: {typo.get('mode')}: {typo.get('reason')}")
        return "fallback", "; ".join(notes)[:140]
    notes.append(f"typo: {len(typo.get('compiled') or [])} unit(s), {typo.get('runs')} run(s)")
    return ("ok" if cold.get("mode") != "full" else "fallback"), "; ".join(notes)[:140]


def main() -> None:
    manifest = {e["id"]: e for e in json.load(open(sys.argv[1]))}
    everything = [json.loads(ln) for ln in open(sys.argv[2]) if ln.strip()]
    rows = [r for r in everything if "prefilter" not in r]
    skipped = [r for r in everything if "prefilter" in r]
    print("| Document | Licence | Class | Variant | Result | Cold s | Typo s | Note |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        e = manifest.get(r["id"], {})
        st, note = status(r)
        print(f"| {r['id']} | {e.get('license', '')} | {e.get('class', '')} | "
              f"{', '.join(r.get('variant', [])) or '-'} | {st} | "
              f"{r.get('cold', {}).get('seconds', '')} | {(r.get('typo') or {}).get('seconds', '')} | "
              f"{note.replace('|', '/')} |")

    if skipped:
        print("\n## Not compiling with pdfLaTeX (pre-filter)\n")
        print("| Document | First error |")
        print("|---|---|")
        for r in skipped:
            repo = r["id"].removeprefix("gh/")
            link = f"[{repo}](https://github.com/{repo})" if r["id"].startswith("gh/") else repo
            print(f"| {link} | {r['prefilter'].replace('|', '/')} |")


main()
