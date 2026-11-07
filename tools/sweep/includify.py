"""Turn a LaTeX document into one with top-level \\include'd chapters (test corpora for chapmk).

    python includify.py MAIN.tex [--inline] [--alias linclude] [--prefix ch]

- ``--inline``: body-level ``\\input{f}`` whose file contains ``\\include`` or ``\\chapter``
  is replaced by the file's text (chapmk only sees includes of the main file).
- ``--alias NAME``: ``\\NAME{f}`` at line start is rewritten to ``\\include{f}``.
- Then each top-level chapter in the main file's body (``\\chapter``, ``\\chapter*``,
  ``\\addchap``; brace depth 0, outside environments and conditionals) up to the next
  structural command is moved to ``<prefix>NN.tex`` and replaced by ``\\include``.

The main file is rewritten in place (work on a copy). Prints the units it made.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from chapmk.texsource import (
    depth_at_line_starts,
    open_conditional_at_line_starts,
    split_lines,
    strip_comment,
)

START = re.compile(r"^\s*\\(chapter\*?|addchap\*?)(?![A-Za-z@])")
BOUNDARY = re.compile(
    r"^\s*\\(chapter|addchap|part|addpart|appendix|frontmatter|mainmatter|backmatter|"
    r"printbibliography|bibliography|printindex|printnomenclature|include|input|"
    r"end\{document\}|begin\{appendices\}|end\{appendices\})(?![A-Za-z@])"
)
INPUT = re.compile(r"^\s*\\input\s*\{([^}]+)\}\s*$")
ENV = re.compile(r"\\(begin|end)\s*\{([^}]+)\}")
VERBATIM = {"verbatim", "verbatim*", "lstlisting", "minted", "comment", "Verbatim"}


def env_depth_at_line_starts(lines: list[str]) -> list[int]:
    """Open environments (other than document) at each line start; verbatim-like ones hide
    their content."""
    depths, depth, verb = [], 0, None
    for line in lines:
        depths.append(depth + (1 if verb else 0))
        if verb is not None:
            if re.search(r"\\end\s*\{" + re.escape(verb) + r"\}", line):
                verb = None
            continue
        for m in ENV.finditer(strip_comment(line)):
            name = m.group(2)
            if name == "document":
                continue
            if m.group(1) == "begin":
                if name in VERBATIM:
                    verb = name
                    break
                depth += 1
            else:
                depth = max(0, depth - 1)
    return depths


def body_range(lines: list[str]) -> tuple[int, int]:
    begin = next(i for i, ln in enumerate(lines) if "\\begin{document}" in strip_comment(ln))
    end = next(i for i in range(len(lines) - 1, -1, -1) if "\\end{document}" in strip_comment(lines[i]))
    return begin + 1, end


def inline_inputs(main: Path, lines: list[str], aliases: list[str]) -> list[str]:
    """Replace \input{f} lines (anywhere, repeatedly) by the text of f if it holds
    \begin{document}, \include, \chapter or an alias."""
    wanted = re.compile(
        r"^\s*\\(include|chapter|"
        + "|".join(re.escape(a.partition(":")[0]) for a in aliases or ["include"])
        + r")\b|\\begin\{document\}",
        re.MULTILINE,
    )
    changed = True
    while changed:
        changed, out = False, []
        for ln in lines:
            m = INPUT.match(strip_comment(ln))
            if m:
                name = m.group(1)
                f = main.parent / (name if name.endswith(".tex") else f"{name}.tex")
                if f.is_file():
                    text = f.read_text(encoding="utf-8", errors="surrogateescape")
                    if wanted.search(text):
                        out += [x if x.endswith("\n") else x + "\n" for x in split_lines(text)]
                        changed = True
                        continue
            out.append(ln)
        lines = out
    return lines


def includify(main: Path, prefix: str, inline: bool, aliases: list[str]) -> list[str]:
    text = main.read_text(encoding="utf-8", errors="surrogateescape")
    lines = split_lines(text)
    if inline:
        lines = inline_inputs(main, lines, aliases)
    for alias in aliases:  # NAME or NAME:SUFFIX (\NAME{f} includes f<SUFFIX>)
        name, _, suffix = alias.partition(":")
        lines = [
            re.sub(rf"^(\s*)\\{name}\s*\{{([^}}]+)\}}", rf"\1\\include{{\2{suffix}}}", ln)
            for ln in lines
        ]
    clean = [strip_comment(ln) for ln in lines]
    braces = depth_at_line_starts(clean)
    conds = open_conditional_at_line_starts(clean)
    envs = env_depth_at_line_starts(lines)
    b, e = body_range(lines)

    def top(i: int) -> bool:  # conditionals opened in the preamble are ignored
        return braces[i] == 0 and (conds[i] == 0 or conds[i] <= b) and envs[i] == 0

    out, made, i, n = lines[:b], [], b, 0
    while i < e:
        if top(i) and START.match(clean[i]):
            j = i + 1
            while j < e and not (top(j) and BOUNDARY.match(clean[j])):
                j += 1
            n += 1
            name = f"{prefix}{n:02d}"
            (main.parent / f"{name}.tex").write_text(
                "".join(lines[i:j]), encoding="utf-8", errors="surrogateescape"
            )
            out.append(f"\\include{{{name}}}\n")
            made.append(f"{name}: lines {i + 1}-{j} ({clean[i].strip()[:50]})")
            i = j
        else:
            out.append(lines[i])
            i += 1
    main.write_text("".join(out + lines[e:]), encoding="utf-8", errors="surrogateescape")
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("main", type=Path)
    ap.add_argument("--prefix", default="ch")
    ap.add_argument("--inline", action="store_true")
    ap.add_argument("--alias", action="append", default=[])
    a = ap.parse_args()
    made = includify(a.main, a.prefix, a.inline, a.alias)
    print("\n".join(made))
    text = a.main.read_text(encoding="utf-8", errors="surrogateescape")
    print(f"{len(made)} units made; {len(re.findall(r"(?m)^\s*\\include\{", text))} includes in {a.main}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
