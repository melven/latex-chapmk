"""Generate the thesis corpus (PLAN §8.1) next to this script. Deterministic; run after
changing it and commit the output: ``python3 tests/corpus/thesis/generate.py``.

main.tex = preamble.tex (the user's preamble, verbatim) + generated body.
"""

from __future__ import annotations

import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORDS = (
    "tensor train rank operator matrix vector solver memory bandwidth cache kernel thread "
    "parallel scaling algorithm iteration residual norm error bound decomposition network "
    "approximation sweep orthogonal core contraction precision accuracy performance model "
    "roofline throughput latency simulation domain grid boundary condition time step"
).split()
N_BIB = 44
N_CITED = 40  # ref01..ref40 are cited by the chapters
CHAPTERS = [
    ("ch1", "Introduction"),
    ("ch2", "Mathematical background"),
    ("ch3", "Data structures"),
    ("ch4", "Algorithms"),
    ("ch5", "Performance analysis"),
    ("ch6", "Applications"),
]
APPENDICES = [("appA", "Additional proofs"), ("appB", "Measurement details")]
NOMENCL_GROUPS = "ABCDEFP"


def words(rng: random.Random, n: int) -> str:
    text = " ".join(rng.choice(WORDS) for _ in range(n))
    return text[0].upper() + text[1:] + "."


def paragraph(rng: random.Random, sentences: int = 7) -> str:
    return " ".join(words(rng, rng.randint(9, 18)) for _ in range(sentences))


def bib() -> str:
    rng = random.Random(1)
    out = []
    for i in range(1, N_BIB + 1):
        kind = ("article", "book", "inproceedings")[i % 3]
        title = words(rng, 6).rstrip(".")
        # uncited entries (ref41..) sort first: citing one renumbers the bibliography (T4)
        surname = "Aaberg" if i > N_CITED else "Author"
        author = f"{surname}{i:02d}, A. and Coauthor{(i * 7) % N_BIB:02d}, B."
        venue = {"article": "journal = {Journal of Examples}, volume = {%d}," % (i % 30 + 1),
                 "book": "publisher = {Example Press},",
                 "inproceedings": "booktitle = {Proceedings of the Example Conference},"}[kind]
        out.append(f"@{kind}{{ref{i:02d},\n  author = {{{author}}},\n  title = {{{title}}},\n"
                   f"  {venue}\n  year = {{{1990 + i % 35}}}\n}}\n")
    return "\n".join(out)


def figure_source(k: int) -> str:
    return (
        "\\documentclass[border=2pt]{standalone}\n\\usepackage{tikz}\n\\begin{document}\n"
        "\\begin{tikzpicture}\n"
        f"\\draw[->] (0,0) -- (4.2,0) node[right] {{$n$}};\n"
        f"\\draw[->] (0,0) -- (0,3.2) node[above] {{$t_{k}$}};\n"
        f"\\draw[thick, domain=0:4, samples=40] plot (\\x, {{3*(1-exp(-{k}*\\x/4))}});\n"
        f"\\node at (2,1) {{figure {k}}};\n"
        "\\end{tikzpicture}\n\\end{document}\n"
    )


def chapter(idx: int, name: str, title: str, appendix: bool = False) -> str:
    rng = random.Random(100 + idx)
    k = idx + 1
    other = (idx + 2) % len(CHAPTERS) + 1  # a different main chapter for cross references
    cites = [f"ref{(idx * 5 + j) % N_BIB + 1:02d}" for j in range(5)]
    g = NOMENCL_GROUPS[idx % len(NOMENCL_GROUPS)]
    parts = [
        f"\\chapter{{{title}}}\\label{{ch:{name}}}",
        paragraph(rng) + f" See \\cite{{{cites[0]}}} and \\cite{{{cites[1]},{cites[2]}}}."
        f"\\footnote{{A footnote in {name} with \\cite{{{cites[3]}}}.}}",
        f"\\section{{Theory of {name}}}\\label{{sec:{name}-theory}}",
        f"\\nomenclature[{g}]{{$a_{{{k}}}$}}{{coefficient of {name}}}"
        f"\\nomenclature[{g}]{{$\\mathbf{{v}}_{{{k}}}$}}{{vector of {name}}}",
        paragraph(rng),
        f"\\begin{{equation}}\\label{{eq:{name}}}\n  x_{{{k}}} = \\sum_{{i=1}}^{{n}} a_i "
        f"\\contract b_i \\in \\Rn, \\quad \\argmin_{{y\\in\\R}} \\| y \\|\n\\end{{equation}}",
        f"\\begin{{theorem}}\\label{{thm:{name}}}\n  {words(rng, 14)}\n\\end{{theorem}}",
        f"\\begin{{lemma}}\n  {words(rng, 10)}\n\\end{{lemma}}",
        paragraph(rng),
        f"\\subsection{{Details of {name}}}\\label{{sub:{name}}}",
        paragraph(rng),
    ]
    if not appendix:
        parts += [
            f"\\section{{Figures of {name}}}",
            paragraph(rng),
            "\\begin{figure}[htb]\n  \\centering\n"
            f"  \\pgfimage[width=0.55\\textwidth]{{plot{k}}}\n"
            f"  \\caption{{Measured curve of {name}}}\\label{{fig:{name}}}\n\\end{{figure}}",
            "\\begin{figure}[htb]\n  \\centering\n"
            "  \\begin{subfigure}{0.45\\textwidth}\\centering\n"
            "    \\begin{tikzpicture}\\draw[gnuplot1, thick] (0,0) rectangle (2,1);"
            "\\node at (1,0.5) {left};\\end{tikzpicture}\n"
            "    \\caption{Left part}\n  \\end{subfigure}\n"
            "  \\begin{subfigure}{0.45\\textwidth}\\centering\n"
            "    \\begin{tikzpicture}\\draw[gnuplot2, thick] (0,0) circle (0.6);"
            "\\node at (0,0) {right};\\end{tikzpicture}\n"
            "    \\caption{Right part}\n  \\end{subfigure}\n"
            f"  \\caption{{Sketches of {name}}}\\label{{fig:{name}-sub}}\n\\end{{figure}}",
            paragraph(rng),
            f"\\section{{Tables of {name}}}",
            "\\begin{table}[htb]\n  \\centering\n"
            f"  \\caption{{Parameters of {name}}}\\label{{tab:{name}}}\n"
            "  \\begin{tabular}{llr}\n    \\toprule\n"
            "    \\multirow{2}{*}{Case} & \\makecell{Memory\\\\traffic} & Rate \\\\\n"
            "    & & \\\\\n    \\midrule\n"
            f"    small & \\SI{{{k}.5}}{{\\GB}} & \\SI{{{k * 3}}}{{\\GFs}} \\\\\n"
            f"    large & \\SI{{{k * 2}}}{{\\TB}} & \\SI{{{k * 7}}}{{\\GBs}} \\\\\n"
            "    \\bottomrule\n  \\end{tabular}\n\\end{table}",
            paragraph(rng),
            f"\\section{{Algorithms of {name}}}",
            "\\begin{algorithm}\n"
            f"  \\caption{{Sweep of {name}}}\\label{{alg:{name}}}\n"
            "  \\begin{algorithmic}[1]\n"
            "    \\REQUIRE tensor $x$, tolerance $\\epsilon$ \\COMMENT{input}\n"
            "    \\FOR{$i = 1, \\dots, d$}\n"
            f"      \\STATE $x_i \\gets x_i / \\| x_i \\|$ \\COMMENT{{normalise core {k}}}\n"
            "    \\ENDFOR\n"
            "    \\ENSURE $x$ \\COMMENT{output}\n"
            "  \\end{algorithmic}\n\\end{algorithm}",
            "\\begin{lstlisting}\n"
            f"// kernel of {name}\n__shared__ double buf[{32 * k}];\n"
            "for (int i = 0; i < n; i++) y[i] += a * x[i];\n"
            "#pragma omp parallel for\n\\end{lstlisting}",
            paragraph(rng),
        ]
    if name == "ch3":
        rows = "\n".join(f"  row {r} & \\SI{{{r}}}{{\\MB}} & {words(rng, 3)} \\\\" for r in range(1, 71))
        parts += [
            "\\section{A long table}\\label{sec:longtable}",
            "\\begin{longtable}{lll}\n  \\caption{Long table of measurements}\\label{tab:long}\\\\\n"
            "  \\toprule Row & Size & Comment \\\\ \\midrule\n  \\endfirsthead\n"
            "  \\toprule Row & Size & Comment \\\\ \\midrule\n  \\endhead\n"
            f"{rows}\n  \\bottomrule\n\\end{{longtable}}",
        ]
    parts += [
        f"\\section*{{Remarks on {name}}}",
        f"As shown in \\autoref{{ch:ch{other}}}, \\nameref{{sec:ch{other}-theory}} and "
        f"\\subsecref{{sec:ch{other}-theory}}, the result \\eqref{{eq:ch{other}}} on "
        f"page~\\pageref{{eq:ch{other}}} carries over; compare \\autoref{{thm:ch{other}}}."
        f"\\todo{{check the remark of {name}}}",
        paragraph(rng),
    ]
    if name == "ch2":
        parts.append("\\foreignlanguage{ngerman}{Dies ist ein kurzer deutscher Absatz über "
                     "Tensoren, Größen und Maßstäbe.}")
    parts.append(paragraph(rng) + f" Further reading: \\cite{{{cites[4]}}}.")
    return "\n\n".join(parts) + "\n"


def main_body() -> str:
    incs = "\n".join(f"\\include{{chapters/{n}}}" for n, _ in CHAPTERS)
    apps = "\n".join(f"\\include{{chapters/{n}}}" for n, _ in APPENDICES)
    return (
        "\n\\title{Fast incremental builds of a synthetic thesis}\n"
        "\\author{A. Author}\n\\date{2026}\n\n"
        "\\begin{document}\n\\frontmatter\n\\maketitle\n\\tableofcontents\n"
        "\\listoffigures\n\\listoftables\n\\listofalgorithms\n\\listoftodos\n"
        "\\printnomenclature\n\\mainmatter\n"
        f"{incs}\n\\appendix\n{apps}\n\\printbibliography\n\\end{{document}}\n"
    )


def generate() -> None:
    preamble = (HERE / "preamble.tex").read_text(encoding="utf-8")
    (HERE / "main.tex").write_text(preamble + main_body(), encoding="utf-8")
    (HERE / "chapters").mkdir(exist_ok=True)
    for idx, (name, title) in enumerate(CHAPTERS):
        (HERE / "chapters" / f"{name}.tex").write_text(chapter(idx, name, title))
    for idx, (name, title) in enumerate(APPENDICES):
        (HERE / "chapters" / f"{name}.tex").write_text(
            chapter(len(CHAPTERS) + idx, name, title, appendix=True))
    (HERE / "fig").mkdir(exist_ok=True)
    for k in range(1, len(CHAPTERS) + 1):
        (HERE / "fig" / f"plot{k}.tex").write_text(figure_source(k))
    (HERE / "thesis.bib").write_text(bib())


if __name__ == "__main__":
    generate()
