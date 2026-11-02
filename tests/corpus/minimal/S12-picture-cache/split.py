"""S12: split exported picture pages of a cache-mode run into fig/<name>.pdf + .dpth.

usage: split.py RUNDIR FIGDIR   (writes RUNDIR/clean.pdf without the extra pages)
A picture is not cached if its page carries annotations or is the target of a named
destination (links/anchors would be lost when embedded) or if aux lines were written
while its copy was shipped (whatsits: \\label, \\addcontentsline, ...).
"""

import re
import sys
from pathlib import Path

import pikepdf

run, fig = Path(sys.argv[1]), Path(sys.argv[2])
fig.mkdir(parents=True, exist_ok=True)
log = (run / "main.log").read_text(errors="replace")
pics = [m.groups() for m in re.finditer(r"^S12PIC (\S+) (\d+) (\S+) (\S+) (\S+) (\S*)\.$", log, re.M)]
serial = re.search(r"^S12SERIALREG \\count(\d+)$", log, re.M)[1]
fenced: dict[str, list[str]] = {}
for aux in run.glob("*.aux"):
    cur = None
    for line in aux.read_text(errors="replace").splitlines():
        m = re.match(r"\\sxiifence\{(/?)(.*)\}$", line)
        if m:
            cur = None if m[1] else m[2]
        elif cur:
            fenced.setdefault(cur, []).append(line)
pdf = pikepdf.open(run / "main.pdf")
targets = set()
if "/Names" in pdf.Root and "/Dests" in pdf.Root.Names:
    for _, d in pikepdf.NameTree(pdf.Root.Names.Dests).items():
        d = d.D if isinstance(d, pikepdf.Dictionary) else d
        targets.add(d[0].objgen)
extra = set()
for name, page, wd, ht, dp, delta in pics:
    page = int(page)
    changes = dict(x.split(":") for x in delta.split(",") if x)
    advance = changes.pop(serial, "0")
    p = pdf.pages[page - 1]
    extra.add(page - 1)
    why = []
    if "/Annots" in p:
        why.append(f"{len(p.Annots)} annotations")
    if p.objgen in targets:
        why.append("destination target")
    if changes:
        why.append(f"changes registers {changes}")
    if name in fenced:
        why.append(f"whatsits {fenced[name]}")
    if why:
        print(f"  {name}: not cached ({'; '.join(why)})")
        continue
    out = pikepdf.new()
    out.pages.append(p)
    out.save(fig / (Path(name).name + ".pdf"))
    total = f"{float(ht[:-2]) + float(dp[:-2]):.5f}pt"
    (fig / (Path(name).name + ".dpth")).write_text(
        f"{dp}\n\\pgfexternal@restore{{\\def\\pgfexternalwidth{{{wd}}}}}\n"
        f"\\pgfexternal@restore{{\\def\\pgfexternalheight{{{total}}}}}\n"
        f"\\pgfexternal@restore{{\\global\\advance\\count{serial} by {advance}\\relax}}\n")
    print(f"  {name}: cached (page {page}, {wd} x {ht} + {dp}, picture ids +{advance})")
for i in sorted(extra, reverse=True):
    del pdf.pages[i]
pdf.save(run / "clean.pdf")
