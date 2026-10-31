"""Create ``fastinc-main.tex``: an adapted single-file main of the unmodified pgf manual.

The upstream files in ``upstream/`` stay unchanged (licence, see README.md). fastinc v1 needs:
- the ``\\include`` commands in the body of the main file (A2): pgfmanual.tex, -main.tex,
  -main-preamble.tex and -main-body.tex are inlined;
- no index (imakeidx/makeindex is not supported in v1): ``\\usepackage{imakeidx}``,
  ``\\makeindex[...]`` and ``\\printindex`` are removed (``\\index`` is then a no-op);
- the ``bookmark`` package for the outline (v1 supports the outline only via bookmark).

Usage: ``python3 adapt.py DIR`` where DIR is a copy of ``upstream/``; writes DIR/fastinc-main.tex.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAIN = "fastinc-main.tex"


def _inline(directory: Path, name: str) -> str:
    text = (directory / name).read_text(encoding="utf-8")

    def repl(m: re.Match[str]) -> str:
        target = m.group(1)
        if target in ("pgfmanual-en-main.tex", "pgfmanual-en-main-preamble.tex",
                      "pgfmanual-en-main-body.tex"):
            return f"% fastinc adapt: inlined {target}\n" + _inline(directory, target)
        return m.group(0)

    return re.sub(r"^\\input\{([^}]+)\}[^\n]*$", repl, text, flags=re.M)


def adapt(directory: Path) -> Path:
    text = _inline(directory, "pgfmanual.tex")
    for pattern, replacement in (
        (r"^\\usepackage\{imakeidx\}", "% fastinc adapt: imakeidx removed"),
        (r"^\\makeindex\[[^\]]*\]", "% fastinc adapt: \\\\makeindex removed"),
        (r"^\\printindex", "% fastinc adapt: \\\\printindex removed"),
        (r"^\\usepackage\{hyperref\}", "\\\\usepackage{hyperref}\\\\usepackage{bookmark}"),
    ):
        text, n = re.subn(pattern, replacement, text, flags=re.M)
        if n != 1:
            raise SystemExit(f"adapt.py: pattern {pattern!r} matched {n} times (upstream changed?)")
    out = directory / MAIN
    out.write_text(text, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(adapt(Path(sys.argv[1])))
