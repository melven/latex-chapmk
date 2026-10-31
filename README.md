# fastinc

Incremental, parallel pdfLaTeX builds for documents split into `\include` units
(specification: `PLAN.md`). Status: milestone M3. After a first (cold) build, an edit inside
one chapter recompiles only that chapter and merges the PDF and SyncTeX file. Edits that change
what other parts see (labels, ToC entries, page count, ...) still trigger a cold rebuild; the
dependency-driven fixpoint follows in M4.

```
fastinc build [MAIN] [--full] [--check] [--report FILE] [--build-dir DIR] [--out-dir DIR] [-v]
fastinc check [MAIN]      # build, then compare with a plain full build (PLAN §3.3)
fastinc clean [MAIN]
```

- The build directory (default `.fastinc/` next to `MAIN`) holds everything generated; only
  `<main>.pdf`, `<main>.synctex.gz` and `<main>.log` are written next to `MAIN` (or to
  `--out-dir`). Plain `latexmk`/`pdflatex` builds in the same directory do not interfere.
- Unsupported documents (PLAN §1) are built in full mode automatically, with the reason printed.
- Requirements: Python >= 3.10, TeX Live (pdflatex, biber, makeindex), pikepdf.
- Optional `fastinc.toml` next to the main file, see `PLAN.md` §6.15.

License: BSD-3-Clause.
