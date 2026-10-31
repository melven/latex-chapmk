# fastinc

Incremental, parallel pdfLaTeX builds for documents split into `\include` units
(specification: `PLAN.md`). Status: milestone M4. After a first (cold) build, only the
chapters affected by an edit are recompiled: the edited compilation unit, units whose
references, citations or entry state (page and counter values) changed, and the glue (front
matter, bibliography) when its inputs changed. The PDF and SyncTeX file are merged from the
runs. Runs are sequential (one run per iteration, later units in one "tail" run); parallel
recompilation with prediction follows in M5.

```
fastinc build [MAIN] [--full] [--check] [--report FILE] [--build-dir DIR] [--out-dir DIR] [-v]
fastinc check [MAIN]      # build, then compare with a plain full build (PLAN §3.3)
fastinc clean [MAIN]
fastinc graph [MAIN] [--format text|dot|json]   # compilation units and dependencies
```

- The build directory (default `.fastinc/` next to `MAIN`) holds everything generated; only
  `<main>.pdf`, `<main>.synctex.gz` and `<main>.log` are written next to `MAIN` (or to
  `--out-dir`). Plain `latexmk`/`pdflatex` builds in the same directory do not interfere.
- Unsupported documents (PLAN §1) are built in full mode automatically, with the reason printed.
- State changes in a chapter body that leak to later chapters (e.g. `\setlength` outside a
  group, PLAN §6.8.4) give a warning; such a chapter is then compiled in every run.
- Requirements: Python >= 3.10, TeX Live (pdflatex, biber, makeindex), pikepdf.
- Optional `fastinc.toml` next to the main file, see `PLAN.md` §6.15.

License: BSD-3-Clause.
