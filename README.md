# fastinc

Incremental, parallel pdfLaTeX builds for documents split into `\include` units
(specification: `PLAN.md`). Status: milestone M1. `fastinc build` runs a full build in a
separate build directory; incremental builds follow in M2/M3.

```
fastinc build [MAIN] [--full] [--build-dir DIR] [--out-dir DIR] [-v]
fastinc clean [MAIN]
```

- The build directory (default `.fastinc/` next to `MAIN`) holds everything generated; only
  `<main>.pdf`, `<main>.synctex.gz` and `<main>.log` are written next to `MAIN` (or to
  `--out-dir`). Plain `latexmk`/`pdflatex` builds in the same directory do not interfere.
- Requirements: Python >= 3.10, TeX Live (pdflatex, biber, makeindex), pikepdf.
- Optional `fastinc.toml` next to the main file, see `PLAN.md` §6.15.

License: BSD-3-Clause.
