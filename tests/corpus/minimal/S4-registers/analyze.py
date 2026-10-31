"""S4: compare \\count vectors at segment boundaries between the full run and partial runs."""
import re
import sys
from collections import Counter
from pathlib import Path

out = Path(sys.argv[1])
names: dict[int, list[str]] = {}
logs = [out / "full" / "main.log"] + [Path(p) for p in sys.argv[2:]]  # + format build log
for line in (ln for log in logs if log.exists() for ln in log.read_text(errors="replace").splitlines()):
    m = re.fullmatch(r"\\(\S+)=\\count(\d+)", line.strip())
    if m:
        names.setdefault(int(m.group(2)), []).append(m.group(1))
names.setdefault(0, ["c@page"])


def load(d: Path) -> dict[tuple[str, str], list[int]]:
    rec = {}
    for line in (d / "main.s4v").read_text().splitlines():
        ev, seg, vals = line.split(" ", 2)
        rec[(ev, seg)] = [int(v) for v in vals.split(",")]
    return rec


def name(i: int) -> str:
    return "/".join(names.get(i, [f"count{i}"]))


full = load(out / "full")
print(f"allocated registers (vector length): {len(full[('base', 'G0')])}")
for want in ("c@LT@tables", "Hy@linkcounter", "c@bookmark@seq@number", "pgf@picture@serial@count"):
    hit = [i for i, n in names.items() if want in n]
    print(f"  {want}: {'count' + str(hit[0]) if hit else 'NOT FOUND'}")
diff_by_reg: Counter[int] = Counter()
for d in sorted(out.glob("p-*")):
    part = load(d)
    bad = []
    for key, vec in part.items():
        if key[0] == "base" or key not in full:
            continue
        ref = full[key]
        regs = [i for i in range(min(len(vec), len(ref))) if vec[i] != ref[i]]
        if regs:
            bad.append((key, regs))
            diff_by_reg.update(regs)
    print(f"{d.name}: {len(part)} records, {len(bad)} differ from the full run")
    for key, regs in bad:
        print(f"   {key[0]:5} {key[1]:14} " + ", ".join(f"{name(i)}" for i in regs[:12]))
print("registers differing (number of records):")
for i, n in diff_by_reg.most_common():
    print(f"  count{i:<5} {name(i):40} {n}")
