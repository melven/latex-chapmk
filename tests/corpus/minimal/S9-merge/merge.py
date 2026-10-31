"""S9: prototype PDF merge (PLAN §6.11) of partial runs into one PDF.

Usage: merge.py OUT.pdf SEGMENTS RUN=DIR... with SEGMENTS "G0=A,U:u1.tex=A,..." (segment -> run).
Each run dir holds main.pdf, main.log, main.aux, main.fpg (s9probe.sty).
"""

import re
import sys
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String

out_path = Path(sys.argv[1])
seg_src = dict(item.split("=") for item in sys.argv[2].split(","))
runs = {k: Path(v) for k, v in (a.split("=") for a in sys.argv[3:])}


class Run:
    def __init__(self, d: Path) -> None:
        self.pdf = pikepdf.open(d / "main.pdf")
        self.fpg = []  # (index, seg, value, label)
        for line in (d / "main.fpg").read_text().splitlines():
            n, seg, val, lab = line.split(" ", 3)
            self.fpg.append((int(n), seg, int(val), lab))
        log = (d / "main.log").read_text(errors="replace")
        self.dummies = set(re.findall(r"name\{([^}]*)\} has been referenced but does not exist", log))
        self.aux = (d / "main.aux").read_text(errors="replace")
        self.pageidx = {p.objgen: i for i, p in enumerate(self.pdf.pages)}


R = {k: Run(d) for k, d in runs.items()}
merged = pikepdf.new()
pmap: dict[tuple[str, int], int] = {}  # (run, page index) -> merged index
labels = []  # (value, label) per merged page
for seg, r in seg_src.items():
    for n, s, val, lab in R[r].fpg:
        if s == seg:
            pmap[(r, n)] = len(merged.pages)
            merged.pages.append(R[r].pdf.pages[n])
            labels.append((val, lab))

# named destinations: keep names whose target page was taken from that run; first in merged order wins
cands: dict[str, tuple[int, Array]] = {}
for r, run in R.items():
    for name, val in pikepdf.NameTree(run.pdf.Root.Names.Dests).items():
        if name in run.dummies:
            continue
        arr = val.D if isinstance(val, Dictionary) else val
        src = run.pageidx[arr[0].objgen]
        if (r, src) not in pmap:
            continue
        m = pmap[(r, src)]
        if name not in cands or m < cands[name][0]:
            cands[name] = (m, arr)
dests = pikepdf.NameTree.new(merged)
for name in sorted(cands):
    m, arr = cands[name]
    dests[name] = Dictionary(D=Array([merged.pages[m].obj, *[merged.copy_foreign(x) if isinstance(x, pikepdf.Object) and x.is_indirect else x for x in list(arr)[1:]]]))
merged.Root.Names = Dictionary(Dests=dests.obj)

# outline from \BKM@entry records of each segment's slice in its run, levels from \sninebkm
def unhex(h: str) -> bytes:
    return bytes.fromhex(h)


def tex_pdfstring(b: bytes) -> bytes:  # TeX octal escapes \ooo and \x -> bytes
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0x5C and i + 3 < len(b) + 0 and b[i + 1 : i + 4].isdigit():
            out.append(int(b[i + 1 : i + 4], 8)); i += 4
        elif b[i] == 0x5C and i + 1 < len(b):
            out.append(b[i + 1]); i += 2
        else:
            out.append(b[i]); i += 1
    return bytes(out)


entries = []  # (level, open, dest, title bytes)
for seg, r in seg_src.items():
    aux = R[r].aux
    lv = {}
    m = re.search(r"\\sninebkm\{([^}]*)\}", aux)
    for kv in (m.group(1).split(",") if m else []):
        if kv:
            i, l = kv.split("="); lv[i] = int(l)
    cur = None
    for line in aux.splitlines():
        sm = re.match(r"\\snineseg\{(.*)\}", line)
        if sm:
            cur = sm.group(1); continue
        bm = re.match(r"\\BKM@entry\{(.*)\}\{([0-9A-F]*)\}$", line)
        if bm and cur == seg:
            keys = dict(re.findall(r"(\w+)(?:=\{?([^,}]*)\}?)?", bm.group(1)))
            entries.append((lv[keys["id"]], "open" in keys, unhex(keys["dest"]).decode(), tex_pdfstring(unhex(bm.group(2)))))
root = merged.make_indirect(Dictionary(Type=Name.Outlines))
stack = [(-10**6, root)]
for level, is_open, dest, title in entries:
    while stack[-1][0] >= level:
        stack.pop()
    parent = stack[-1][1]
    item = merged.make_indirect(Dictionary(Title=String(title), Parent=parent,
                                           A=Dictionary(S=Name.GoTo, D=String(dest))))
    item["/_open"] = is_open
    if "/Last" in parent:
        parent.Last.Next = item; item.Prev = parent.Last
    else:
        parent.First = item
    parent.Last = item
    stack.append((level, item))


def count(node) -> int:  # visible descendants, PDF /Count semantics
    n, c = 0, node.get("/First")
    while c is not None:
        sub = count(c)
        is_open = bool(c["/_open"]); del c["/_open"]
        if "/First" in c:
            c.Count = sub if is_open else -sub
        n += 1 + (sub if is_open else 0)
        c = c.get("/Next")
    return n


root.Count = count(root)
merged.Root.Outlines = root

# page labels from the page map
def roman(n: int) -> str:
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    s = ""
    for v, t in vals:
        while n >= v:
            s += t; n -= v
    return s


def style(val: int, lab: str):
    if lab == str(val): return "/D"
    if lab == roman(val): return "/r"
    if lab == roman(val).upper(): return "/R"
    return None


nums, prev = [], None
for i, (val, lab) in enumerate(labels):
    st = style(val, lab)
    if st is None:
        nums += [i, Dictionary(P=String(lab))]; prev = None; continue
    if prev and prev[0] == st and val == prev[1] + 1:
        prev = (st, val); continue
    nums += [i, Dictionary(S=Name(st), St=val)]; prev = (st, val)
merged.Root.PageLabels = Dictionary(Nums=Array(nums))

# catalog entries and Info from the run that supplied G0
g0 = R[seg_src["G0"]].pdf
for key in ("/PageMode", "/PageLayout", "/ViewerPreferences"):
    if key in g0.Root:
        merged.Root[key] = merged.copy_foreign(g0.Root[key]) if g0.Root[key].is_indirect else g0.Root[key]
if "/OpenAction" in g0.Root:
    oa = g0.Root.OpenAction
    if isinstance(oa, Array) and len(oa) and isinstance(oa[0], Dictionary):
        merged.Root.OpenAction = Array([merged.pages[pmap[(seg_src["G0"], g0.pages.index(oa[0]))]].obj, *list(oa)[1:]])
merged.docinfo = merged.copy_foreign(g0.docinfo)
merged.save(out_path)
print(f"merged {len(merged.pages)} pages, {len(cands)} destinations, {len(entries)} outline items -> {out_path}")
