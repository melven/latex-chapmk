"""S10: prototype SyncTeX merge (PLAN §6.12).

Usage: merge_synctex.py OUT.synctex.gz PAGES RUN=DIR...
PAGES: comma-separated "run:index" (0-based source page) in merged order.
Rewrites input tags to a global table keyed by path, renumbers sheets, recomputes the
"!<bytes>" offset records and the postamble.
"""

import gzip
import re
import sys
from pathlib import Path

out = Path(sys.argv[1])
pages = [(r, int(i)) for r, i in (p.split(":") for p in sys.argv[2].split(","))]
runs = {k: Path(v) for k, v in (a.split("=") for a in sys.argv[3:])}

HEADER_KEYS = ("Output", "Magnification", "Unit", "X Offset", "Y Offset")
TAGGED = re.compile(r"^([\[(hgkx$vr])(\d+),")


def parse(path: Path):
    lines = gzip.open(path).read().decode("utf-8", "surrogateescape").split("\n")
    inputs, header, sheets, cur = {}, {}, {}, None
    for line in lines:
        if line.startswith("Input:"):
            _, tag, p = line.split(":", 2)
            inputs[tag] = p
        elif cur is None and ":" in line and line.split(":", 1)[0] in HEADER_KEYS:
            k, v = line.split(":", 1)
            header[k] = v
        elif m := re.fullmatch(r"\{(\d+)", line):
            cur = int(m.group(1)); sheets[cur] = []
        elif re.fullmatch(r"\}\d+", line):
            cur = None
        elif cur is not None and line and not line.startswith("!"):
            sheets[cur].append(line)
    return inputs, header, sheets


parsed = {k: parse(d / "main.synctex.gz") for k, d in runs.items()}
headers = {tuple(sorted(h.items())) for _, h, _ in parsed.values()}
if len(headers) != 1:
    sys.exit(f"inconsistent SyncTeX headers: {headers}")
header = dict(next(iter(headers)))

gtags: dict[str, int] = {}  # path -> global tag
def gtag(path: str) -> int:
    # keep pdfTeX's "<abs cwd>/./<relative>" form: synctex view matches relative names by it
    return gtags.setdefault(path, len(gtags) + 1)

body, count = [], 0
for n, (r, i) in enumerate(pages, start=1):
    inputs, _, sheets = parsed[r]
    body.append(f"{{{n}")
    for line in sheets[i + 1]:
        m = TAGGED.match(line)
        if m:
            line = f"{m.group(1)}{gtag(inputs[m.group(2)])}," + line[m.end():]
        if line[0] not in "]":
            count += 1
        body.append(line)
    body.append(f"}}{n}")

# serialise with "!<bytes since previous ! line>" before every sheet open/close and the postamble
text = ["SyncTeX Version:1"] + [f"Input:{t}:{p}" for p, t in gtags.items()]
text += [f"{k}:{header[k]}" for k in HEADER_KEYS] + ["Content:"]
buf = "\n".join(text) + "\n"
last = 0
def bang(s: str) -> str:
    global last
    pos = len(s.encode("utf-8", "surrogateescape"))
    rec = f"!{pos - last}\n"
    last = pos
    return s + rec
for line in body:
    if line[0] in "{}":
        buf = bang(buf)
    buf += line + "\n"
buf = bang(buf) + f"Postamble:\nCount:{count}\n"
buf = bang(buf) + "Post scriptum:\n"
with gzip.open(out, "wb") as f:
    f.write(buf.encode("utf-8", "surrogateescape"))
print(f"merged {len(pages)} sheets, {len(gtags)} inputs -> {out}")
