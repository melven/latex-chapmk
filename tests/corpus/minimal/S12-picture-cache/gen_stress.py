"""S12: stress document with many pictures of different kinds and positions.

usage: gen_stress.py OUTDIR [UNITS] [PER_UNIT] [KIND]   (KIND: only pictures of this kind)
"""

import sys
from pathlib import Path

out = Path(sys.argv[1])
units = int(sys.argv[2]) if len(sys.argv) > 2 else 3
per = int(sys.argv[3]) if len(sys.argv) > 3 else 12
only = sys.argv[4] if len(sys.argv) > 4 else None
out.mkdir(parents=True, exist_ok=True)

KINDS = [
    # (name, picture code); {i} is a running number
    ("plot", r"\begin{tikzpicture}\draw[domain=0:6,samples=400,smooth] plot (\x,{sin((\x+{i})*1 r)});"
     r"\node[below] at (3,-1) {plot {i}};\end{tikzpicture}"),
    ("pgfplots", r"\begin{tikzpicture}\begin{axis}[width=6cm,height=4cm,xlabel={$x$},ylabel={$f(x)$},"
     r"title={Axis {i}}]\addplot[domain=0:{i}+1,samples=80]{x^2/({i}+1)};\addplot+[only marks]"
     r" coordinates {(0,1) (1,{i}) (2,3)};\legend{a,b}\end{axis}\end{tikzpicture}"),
    ("opacity", r"\begin{tikzpicture}\fill[red,opacity=0.4] (0,0) circle (1);\fill[blue,opacity=0.4]"
     r" (0.8,0) circle (1);\node at (0.4,0) {$\cap_{i}$};\end{tikzpicture}"),
    ("shading", r"\begin{tikzpicture}\shade[left color=yellow,right color=green!50!black,rounded corners]"
     r" (0,0) rectangle (4,1);\shade[ball color=blue] (5,0.5) circle (0.5);\end{tikzpicture}"),
    ("pattern", r"\begin{tikzpicture}\fill[pattern=north east lines,pattern color=gray] (0,0) rectangle (3,1);"
     r"\draw[dashed,->,>=stealth,thick] (0,0) -- (3,1) node[right] {\footnotesize arrow {i}};\end{tikzpicture}"),
    ("graph", r"\begin{tikzpicture}[every node/.style={draw,circle,inner sep=1pt}]\node (a) at (0,0) {A};"
     r"\node (b) at (2,0.5) {B};\node (c) at (1,-1) {$\int_0^{i} x\,dx$};\draw[->] (a) to[bend left] (b);"
     r"\draw[->] (b) -- (c) -- (a);\end{tikzpicture}"),
    ("image", r"\begin{tikzpicture}\node[inner sep=0] {\includegraphics[width=2cm]{example-image-a}};"
     r"\draw[red,thick] (-1,-0.7) rectangle (1,0.7);\end{tikzpicture}"),
    ("scaled", r"\begin{tikzpicture}[scale=0.37,transform shape]\node[draw,fill=gray!20] {scaled node {i}};"
     r"\draw (0,-1) sin (1,0) cos (2,-1);\end{tikzpicture}"),
]

PLACES = [
    ("figure", "\\begin{{figure}}[htbp]\\centering\n{pic}\n\\caption{{Figure {i}}}\\label{{fig:{i}}}\n\\end{{figure}}\n"),
    ("inline", "Inline {pic} picture within a sentence that goes on for a while, number {i}.\n"),
    ("baseline", "Baseline \\tikz[baseline=(x.base)]\\node[draw](x){$y_\\theta^2$}; text, and {pic}\n"),
    ("itemize", "\\begin{{itemize}}\\item An item with a picture:\\par {pic}\\item end\\end{{itemize}}\n"),
    ("table", "\\begin{{tabular}}{{|c|c|}}\\hline left & {pic}\\\\\\hline\\end{{tabular}}\n"),
    ("center", "\\begin{{center}}{pic}\\end{{center}}\n"),
]

LIPSUM = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt "
          "ut labore et dolore magna aliqua. ")

n = 0
names = []
for u in range(1, units + 1):
    body = [f"\\chapter{{Unit {u}}}\n"]
    for k in range(per):
        n += 1
        kind, code = next(k for k in KINDS if k[0] == only) if only else KINDS[n % len(KINDS)]
        place, tpl = PLACES[(n // len(KINDS) + n) % len(PLACES)]
        pic = code.replace("{i}", str(n))
        if k % 4 == 0:
            body.append(f"\\section{{Section {n}}}\n")
        body.append(LIPSUM * (1 + n % 3) + "\n\n")
        body.append(tpl.replace("{{", "\x00").replace("}}", "\x01").replace("{pic}", pic).replace("{i}", str(n)).replace("\x00", "{").replace("\x01", "}") + "\n")
    name = f"s{u}"
    names.append(name)
    (out / f"{name}.tex").write_text("".join(body))

(out / "main.tex").write_text(
    "\\documentclass[twoside,openright]{scrbook}\n\\usepackage[T1]{fontenc}\n\\usepackage{lmodern}\n"
    "\\usepackage{graphicx}\n\\usepackage{tikz}\n\\usetikzlibrary{patterns}\n\\usepackage{pgfplots}\n"
    "\\pgfplotsset{compat=1.18}\n\\usepackage{hyperref}\n\\begin{document}\n\\tableofcontents\n"
    + "".join(f"\\include{{{x}}}\n" for x in names)
    + "\\end{document}\n"
)
print(f"{n} pictures in {units} units")
