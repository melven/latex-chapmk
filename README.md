# latex-chapmk

[![ci](https://github.com/melven/latex-chapmk/actions/workflows/ci.yml/badge.svg)](https://github.com/melven/latex-chapmk/actions/workflows/ci.yml)

`chapmk`: latexmk for books. It rebuilds only the changed `\include`'d chapters of a pdfLaTeX
document, in parallel, and merges them into one PDF and SyncTeX file that look like a plain
full build (`chapmk check` verifies this).

## Install

```
pip install latex-chapmk          # or: pip install git+https://github.com/melven/latex-chapmk
```

Needs Python ≥ 3.11 and TeX Live with `pdflatex`, `biber` and `makeindex`. `chapmk check`
also needs `pdfinfo`, `pdftoppm`, `pdftotext` (poppler-utils) and `synctex` (TeX Live).
The LaTeX packages chapmk uses are part of the Python package; nothing is installed into TeX.

## Usage

```
chapmk build [MAIN] [-j N] [--full] [--check] [--report FILE] [-v]
chapmk check [MAIN]                            # build, plain full build, compare
chapmk graph [MAIN] [--format text|dot|json]   # compilation units and dependencies
chapmk clean [MAIN]
```

- Writes `<main>.pdf`, `.synctex.gz` and `.log` next to `MAIN`; everything else goes to
  `.chapmk/<jobname>/`. Plain latexmk builds in the same directory do not interfere.
- Exit codes: 0 ok, 1 TeX error (or `check` found a difference), 2 other error, 3 internal
  error, 130/143 interrupted. One build per document at a time (a second one waits).
- `--report FILE`: JSON with the runs, why each chapter was recompiled, and times.
- Optional `chapmk.toml` next to the main file: [docs/configuration.md](docs/configuration.md).

## Editor setup

- **VS Code (LaTeX Workshop):** tool `{"name": "chapmk", "command": "chapmk", "args":
  ["build", "%DOCFILE_EXT%"]}`, recipe `{"name": "chapmk", "tools": ["chapmk"]}`.
- **TeXstudio:** Options → Build → user command `chapmk build %.tex`, set as default compiler.
- **vimtex:** `let g:vimtex_compiler_method = 'generic'` and
  `let g:vimtex_compiler_generic = {'command': 'chapmk build main.tex'}`.

Forward and inverse search work with the published `main.synctex.gz`; the log has the
source paths. If the editor stops a running build (e.g. on the next save), chapmk stops its
TeX processes; a second build of the same document waits for the first.

## How it works

The preamble is precompiled into a format. Each `\include` starting with a chapter-level
heading is a compilation unit. chapmk records what every unit reads and writes (counters,
labels, citations, list entries, running heads) and recompiles only the units whose sources
or inputs changed, several at a time with predicted start states. The pages of all runs are
merged; any case it cannot handle falls back to a plain full build.

## Document assumptions

1. Macro definitions and settings are in the preamble; chapter bodies change only counters,
   labels, citations, list and nomenclature entries. Violations (e.g. `\setlength` outside a
   group) give a warning, and that chapter is then compiled in every run.
2. Units are the `\include`s in the top-level body of the main file (no `..` or absolute
   paths, no spaces).
3. Edits of the main-file body, the include list, a `.bib` file or files read by the
   preamble rebuild everything.
4. No footnote is split across an `\include` boundary.
5. An `\include` that does not start with a chapter-level heading is compiled together with
   the preceding one.

## Limitations

- pdfLaTeX and TeX Live only (MiKTeX, Windows and macOS are not tested yet); biblatex with
  biber only; hyperref needs the `bookmark` package.
- Full builds (like latexmk, with a warning): `glossaries`, `imakeidx`/`makeidx`, `minted`,
  `cleveref`, BibTeX, primitive `\mark`, and cases chapmk cannot verify.
- TikZ externalize: chapmk keeps `\tikzexternalize` but makes the figures itself (no shell
  escape); the result equals an externalized build. References hidden in macros inside
  pictures, and label or citation keys built by macros, are not tracked.
- Dates (`\today`, PDF dates) are fixed at the first build. The merged PDF is larger than a
  plain one (fonts per run): use `chapmk build --full` for the final version.
- chapmk uses one of TeX's 16 write streams.

## Troubleshooting

- `chapmk check` compares the result with a plain full build; `-v` shows why each chapter
  was rebuilt; `chapmk clean` starts over.
- Bugs: please open an issue with the output of `chapmk check` and `-v`
  ([CONTRIBUTING.md](CONTRIBUTING.md)). Do not attach private documents.

## License

BSD-3-Clause ([LICENSE](LICENSE)). Test corpora have their own licences (`REUSE.toml`).
