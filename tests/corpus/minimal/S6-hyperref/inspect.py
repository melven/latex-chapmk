"""S6: print named destinations, outline, link annotations and page labels of a PDF."""
import sys
import pikepdf

pdf = pikepdf.open(sys.argv[1])
pages = {p.objgen: i for i, p in enumerate(pdf.pages)}
names = pdf.Root.Names.Dests
print("Dests tree root keys:", sorted(names.keys()))
tree = pikepdf.NameTree(names)
def target(v):  # explicit array or << /D [...] >>
    arr = v.get("/D") if isinstance(v, pikepdf.Dictionary) else v
    return f"p{pages.get(arr[0].objgen, '?')} {arr[1]} {[None if x is None else float(x) for x in arr[2:]]}"
dests = {str(k): target(v) for k, v in tree.items()}
print("dest value form:", "dict /D" if isinstance(next(iter(tree.values())), pikepdf.Dictionary) else "array")
print(f"{len(dests)} named destinations:")
for k, v in dests.items():
    print(f"  {k:28} {v}")
with pdf.open_outline() as o:
    def walk(items, d=0):
        for it in items:
            print(f"  outline {'  ' * d}{it.title!r} dest={it.destination} open={it.is_closed is False}")
            walk(it.children, d + 1)
    walk(o.root)
for i, p in enumerate(pdf.pages):
    for a in p.get("/Annots", []):
        if a.get("/Subtype") == "/Link":
            act = a.get("/A")
            tgt = act.get("/D") if act is not None and "/D" in act else (act.get("/URI") if act is not None else a.get("/Dest"))
            print(f"  link p{i} -> {tgt}")
print("labels:", [pikepdf.Page(p).label for p in pdf.pages])
