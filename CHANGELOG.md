# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [0.9.0] - unreleased

First test release (formerly developed as `fastinc`).

### Added

- `chapmk build`: incremental, parallel pdfLaTeX builds for documents split with `\include`.
  - The preamble is precompiled into a format; compilation units are the `\include`s that
    start with a chapter-level heading.
  - Each unit's inputs and outputs are recorded: counters, labels, citations, list and
    nomenclature entries, running-head marks, files read.
  - Only affected units are recompiled, several at a time with predicted start states,
    until a fixpoint is reached.
  - The pages of all runs are merged into one PDF with outline, links and page labels, and
    one SyncTeX file.
- biblatex with biber (`.bcf` patched per run), nomencl with makeindex, list files of any
  extension (`.toc`, `.lof`, `.loa`, `\DeclareNewTOC` …), eqparbox.
- TikZ externalize: figures are made and reused by chapmk without shell escape; the result
  equals an externalized latexmk build.
- `chapmk check`: compares the result with a plain full build (rendered pages, text, page
  labels, outline, links, SyncTeX in both directions).
- `chapmk build --full`, `chapmk clean`, `--report` (JSON with the reason each unit was
  recompiled and the time per phase), `chapmk.toml` (docs/configuration.md).
- A lint for unit bodies that change macros or lengths outside groups, and hints for slow
  parts of the main file that could become `\include`s.
- Robustness:
  - one build per build directory (others wait, or `--no-wait`);
  - atomic writes and a commit journal (an interrupted build is redone, never read
    half-written);
  - SIGTERM/SIGINT stop all TeX processes;
  - a stale state after a chapmk upgrade or a TeX package update gives a cold build.
- Exit codes 0 / 1 (TeX error or check difference) / 2 / 3 (internal error) / 130 / 143.
- The published log is composed in document order from the runs (messages as in a full build,
  preamble from the format build).
- `--print-log` writes the log to stdout, also after a TeX error, for editors that parse only
  the build output (VS Code LaTeX Workshop: errors and warnings of all runs), followed by the
  last biber run's output (biber's warnings and errors, as in latexmk's output).
- A missing `mylatexformat` is reported at startup with how to install it (TeX Live:
  `tlmgr`; MiKTeX: MiKTeX Console or `miktex packages install`, unless MiKTeX installs missing
  packages on the fly). An error that TeX writes only to the terminal (e.g. a missing file on
  the command line, where the log only says `! Emergency stop.`) is shown instead of that
  generic stop.

### Known limitations

- pdfLaTeX only. Tested with TeX Live on Linux and MiKTeX on Linux and Windows; macOS is not
  tested yet.
- Full builds (with a warning) for (most common first):
  - BibTeX and biblatex backends other than biber;
  - the packages `glossaries`, `acronym`, `minted`, `imakeidx`, `perpage` (also through
    `footmisc`'s `perpage` option and `bigfoot`), `hyperxmp`;
  - hyperref without `bookmark`;
  - primitive `\mark`;
  - cases chapmk cannot verify.
- Edits of the main-file body, the include list, a `.bib` file or files read by the preamble
  give a cold build.
- Label or citation keys built by macros, and references hidden in macros inside TikZ
  pictures, are not tracked.
- Dates are fixed at the first build; the merged PDF is larger than a plain one.

[0.9.0]: https://github.com/melven/latex-chapmk/releases/tag/v0.9.0
