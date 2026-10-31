"""S8: inventory of aux line kinds per file and (for the main aux) per segment."""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

d = Path(sys.argv[1])


def kind(line: str) -> str:
    line = line.strip()
    m = re.match(r"\\@writefile\{([^}]*)\}", line)
    if m:
        return f"\\@writefile{{{m.group(1)}}}"
    m = re.match(r"\\(?:gdef|def|xdef|global\\def)\s*\\([A-Za-z@]+)", line)
    if m:
        name = re.sub(r"[ivxlcdm]+$", "<roman>", m.group(1)) if m.group(1).startswith("LT@") else m.group(1)
        return f"\\gdef\\{name}"
    m = re.match(r"\\(?:providecommand|newcommand)\*?\s*\{?\\([A-Za-z@]+)", line)
    if m:
        return f"\\providecommand\\{m.group(1)}"
    m = re.match(r"\\setcounter\{([^}]*)\}", line)
    if m:
        return "\\setcounter{...}"
    m = re.match(r"\\([A-Za-z@]+)", line)
    return f"\\{m.group(1)}" if m else repr(line[:30])


seg_kinds: dict[str, Counter[str]] = defaultdict(Counter)
seg = "(before G0)"
for line in (d / "main.aux").read_text(errors="replace").splitlines():
    m = re.match(r"\\seight@seg\{(.*)\}", line)
    if m:
        seg = m.group(1)
        continue
    seg_kinds[seg][kind(line)] += 1
print("== main.aux by segment")
for s, c in seg_kinds.items():
    print(f"  [{s}] " + ", ".join(f"{k}×{n}" for k, n in sorted(c.items())))
if sys.argv[2:] == ["main-only"]:
    sys.exit(0)
print("== unit aux files")
total: Counter[str] = Counter()
for f in sorted(d.glob("u*.aux")):
    c = Counter(kind(l) for l in f.read_text(errors="replace").splitlines() if l.strip())
    total.update(c)
    print(f"  {f.name}: " + ", ".join(f"{k}×{n}" for k, n in sorted(c.items())))
print("== examples (first line of each kind, all files)")
seen = set()
for f in [d / "main.aux", *sorted(d.glob("u*.aux"))]:
    for l in f.read_text(errors="replace").splitlines():
        k = kind(l)
        if k not in seen:
            seen.add(k)
            print(f"  {k:40} {f.name}: {l[:110]}")
