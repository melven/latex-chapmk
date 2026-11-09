"""S19 spike documents: readers that see an anchor of an earlier file."""

import sys
from pathlib import Path

out = Path(sys.argv[1])
BIB = "\\usepackage[backend=biber]{biblatex}\\addbibresource{r.bib}"
CASES = {
    # name: (class, options, text after the last include, unit start, preamble extra)
    "koma": ("scrbook", "listof=totoc", "\\listoffigures", None, ""),
    "komafix": ("scrbook", "listof=totoc", "\\cleardoublepage\\phantomsection\\listoffigures", None, ""),
    "manual": (
        "book",
        "",
        "\\cleardoublepage\\addcontentsline{toc}{chapter}{REFERENCES}\\label{refs}"
        "REFS \\ref{refs} \\nameref{refs}",
        None,
        "",
    ),
    "manualfix": (
        "book",
        "",
        "\\cleardoublepage\\phantomsection\\addcontentsline{toc}{chapter}{REFERENCES}REFS",
        None,
        "",
    ),
    "bookstar": ("book", "", "", "\\chapter*{Star}\\addcontentsline{toc}{chapter}{Star}", ""),
    "komastar": ("scrbook", "", "", "\\chapter*{Star}\\addcontentsline{toc}{chapter}{Star}", ""),
    "komastarfix": (
        "scrbook",
        "",
        "",
        "\\chapter*{Star}\\phantomsection\\addcontentsline{toc}{chapter}{Star}",
        "",
    ),
    "addchap": ("scrbook", "", "", "\\addchap{Star}", ""),
    "bib": ("scrbook", "", "\\printbibliography[heading=bibintoc]", None, BIB),
    "bibbook": ("book", "", "\\printbibliography[heading=bibintoc]", None, BIB),
}
for name, (cls, opts, after, start, extra) in CASES.items():
    d = out / name
    d.mkdir(parents=True)
    (d / "main.tex").write_text(
        f"\\documentclass[{opts}]{{{cls}}}\n\\usepackage[T1]{{fontenc}}\n\\usepackage{{lipsum}}\n"
        f"{extra}\n\\usepackage{{hyperref}}\n\\usepackage{{bookmark}}\n\\begin{{document}}\n"
        f"\\tableofcontents\n\\include{{a}}\n\\include{{b}}\n\\include{{c}}\n{after}\n"
        "\\end{document}\n"
    )
    cite = " \\cite{k}" if extra else ""
    for u in "abc":
        head = start if (start and u != "a") else f"\\chapter{{Chap {u}}}"
        (d / f"{u}.tex").write_text(
            f"{head}\n\\section{{First of {u}}}\nText {u}.{cite} \\lipsum[1-3]\n"
            f"\\begin{{figure}}[h]\\rule{{2cm}}{{1cm}}\\caption{{Fig {u}}}\\end{{figure}}\n"
            f"\\section{{Last of {u}}}\n\\lipsum[4-6]\n"
        )
    if extra:
        (d / "r.bib").write_text("@book{k,author={A},title={T},year={2000},publisher={P}}\n")
