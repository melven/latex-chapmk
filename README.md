# fastinc

Drop-in replacement for `latexmk -pdf -synctex=1` that rebuilds faster after small edits:
the preamble is precompiled into a format, only the `\include` units affected by an edit are
recompiled (in parallel), and the per-run PDFs and SyncTeX files are merged into one
`main.pdf` / `main.synctex.gz`. The output looks the same as a plain full build (checked by
`fastinc check`). Specification: `PLAN.md`.

```
fastinc build [MAIN] [-j N] [--full] [--check] [--report FILE] [--build-dir DIR] [--out-dir DIR] [-v]
fastinc check [MAIN]                            # build + plain full build, compare
fastinc graph [MAIN] [--format text|dot|json]   # compilation units and dependencies
fastinc clean [MAIN]
```

- Generated files go to `.fastinc/`; only `<main>.pdf`, `.synctex.gz` and `.log` are
  written next to `MAIN`. Plain latexmk builds in the same directory do not interfere.
- `-j N`: parallel pdflatex runs (default: CPU count). `--report`: JSON with the runs, the
  reason each unit was recompiled and the time per phase.
- Optional `fastinc.toml` next to the main file (`PLAN.md` §6.15).
- Requirements: Python ≥ 3.10, TeX Live (pdflatex, biber, makeindex), pikepdf.

**Document assumptions** (checked where possible):
1. Macro definitions and settings are in the preamble; chapter bodies change only counters,
   labels, citations, list and nomenclature entries. Violations (e.g. `\setlength` outside a
   group) give a warning, and that chapter is then compiled in every run.
2. Units are the `\include`s in the top-level body of the main file.
3. Edits of the main file body rebuild everything.
4. No footnote is split across an `\include` boundary.
5. Every compilation unit starts with a chapter-level heading; an `\include` that does not
   is compiled together with the preceding one.

**Limitations:** pdfLaTeX only; biblatex with biber only; hyperref needs the `bookmark`
package. Documents using `glossaries`, `imakeidx`/`makeidx`, `minted` or `cleveref` are built
in full mode (like latexmk), with the reason printed.

**Slow glue:** fastinc reports parts of the main file outside `\include`s that cost time in every
run (e.g. a long bibliography) and whether they can move into an `\include`'d file.

**TikZ externalize:** if the document calls `\tikzexternalize`, fastinc keeps it but makes the
figures itself (no shell escape, figures in the build directory; the prefix and system call
are ignored). Unchanged pictures are reused; the result equals a latexmk build with
externalize. `[pictures] cache = false` in `fastinc.toml` typesets all pictures inline instead.

License: BSD-3-Clause.
