# latex-chapmk

[![Python 3.11](https://github.com/melven/latex-chapmk/actions/workflows/python-3.11.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/python-3.11.yml?query=branch%3Amain)
[![Python 3.12](https://github.com/melven/latex-chapmk/actions/workflows/python-3.12.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/python-3.12.yml?query=branch%3Amain)
[![Python 3.13](https://github.com/melven/latex-chapmk/actions/workflows/python-3.13.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/python-3.13.yml?query=branch%3Amain)
[![Python 3.14](https://github.com/melven/latex-chapmk/actions/workflows/python-3.14.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/python-3.14.yml?query=branch%3Amain)
[![TeX Live (2026-11-03)](https://github.com/melven/latex-chapmk/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/ci.yml?query=branch%3Amain)
[![TeX Live 2025](https://github.com/melven/latex-chapmk/actions/workflows/texlive-2025.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/texlive-2025.yml?query=branch%3Amain)
[![TeX Live (current)](https://github.com/melven/latex-chapmk/actions/workflows/texlive-current.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/texlive-current.yml?query=branch%3Amain)
[![MiKTeX (current)](https://github.com/melven/latex-chapmk/actions/workflows/miktex-current.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/miktex-current.yml?query=branch%3Amain)
[![MiKTeX Linux](https://github.com/melven/latex-chapmk/actions/workflows/miktex-linux.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/miktex-linux.yml?query=branch%3Amain)
[![MiKTeX Windows](https://github.com/melven/latex-chapmk/actions/workflows/miktex-windows.yml/badge.svg?branch=main)](https://github.com/melven/latex-chapmk/actions/workflows/miktex-windows.yml?query=branch%3Amain)
[![coverage](https://melven.github.io/latex-chapmk/coverage.svg)](https://melven.github.io/latex-chapmk/)
[![license](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

`chapmk`: latexmk for books. It rebuilds only the changed `\include`'d chapters of a pdfLaTeX
document, in parallel, and merges them into one PDF and SyncTeX file that look like a plain
full build (`chapmk check` verifies this). Speeds up recompiling after small changes from
minutes to <5 seconds.

## Declaration of AI usage

Most of this software was generated using the AI model Claude Opus 5.5 (with effort = High).

## Install

```
pip install git+https://github.com/melven/latex-chapmk
```

Needs Python ≥ 3.11 with pikepdf ≥ 10 and TeXLive/MiKTeX ≥ 2025 with `pdflatex`, `biber`, `makeindex` and the
package `mylatexformat`. `chapmk check` also needs `pdfinfo`, `pdftoppm`, `pdftotext`
(poppler-utils) and `synctex` (part of TeX Live and MiKTeX).
The LaTeX packages chapmk uses are part of the Python package; nothing is installed into TeX.

## Usage

*Warning:* `chapmk` was only tested on a small subset of LaTeX packages. Please verify with
`chapmk check [MAIN]` that your document and setup is supported, and [report any problems](https://github.com/melven/latex-chapmk/issues).

```
chapmk build [MAIN] [-j N] [--full] [--check] [--report FILE] [--print-log] [-v]
chapmk check [MAIN]                            # build, plain full build, compare
chapmk graph [MAIN] [--format text|dot|json]   # compilation units and dependencies
chapmk clean [MAIN]
```

- Writes `<main>.pdf`, `.synctex.gz` and `.log` next to `MAIN`; everything else goes to
  `.chapmk/<jobname>/`. Plain latexmk builds in the same directory do not interfere.
- Exit codes: 0 ok, 1 TeX error (or `check` found a difference), 2 other error, 3 internal
  error, 130/143 interrupted. One build per document at a time (a second one waits).
- `--report FILE`: JSON with the runs, why each chapter was recompiled, and times.
- `--print-log`: also write the log and biber's output to stdout (also after an error), for
  editors that parse only the output of the build command.
- Optional `chapmk.toml` next to the main file: [docs/configuration.md](https://github.com/melven/latex-chapmk/blob/main/docs/configuration.md).

## Editor setup

- **VS Code (LaTeX Workshop):** tool `{"name": "chapmk", "command": "chapmk", "args":
  ["build", "--print-log", "%DOCFILE_EXT%"]}`, recipe `{"name": "chapmk", "tools": ["chapmk"]}`.
  LaTeX Workshop reads errors and warnings only from the output of the build command, not
  from the `.log` file; `--print-log` writes the log there.
- **TeXstudio:** Options → Build → user command `chapmk build %.tex`, set as default compiler.
- **vimtex:** `let g:vimtex_compiler_method = 'generic'` and
  `let g:vimtex_compiler_generic = {'command': 'chapmk build main.tex'}`.

Forward and inverse search work with the published `main.synctex.gz`; the log has the
source paths. If the editor stops a running build (e.g. on the next save), chapmk stops its
TeX processes; a second build of the same document waits for the first.

## Windows

- **MiKTeX:** install the package `mylatexformat`, or let MiKTeX install missing packages on
  the fly ("Always" in MiKTeX Console). The setting "Ask" is refused: it would stop
  unattended and parallel runs.
- **Antivirus:** Windows Defender may scan every file chapmk reads or writes in `.chapmk\`.
  (Re)building can get faster by more than a factor of 3 using a Windows 11
  [Dev Drive](https://learn.microsoft.com/windows/dev-drive/) where Defender
  scans asynchronously; keep the project on a Dev Drive, or exclude its `.chapmk` directory
  from scanning.

## How it works

The preamble is precompiled into a format. Each `\include` starting with a chapter-level
heading is a compilation unit. chapmk records what every unit reads and writes (counters,
labels, citations, list entries, running heads) and recompiles only the units whose sources
or inputs changed, several at a time with predicted start states. The pages of all runs are
merged; any case it cannot handle falls back to a plain full build.
Details: [docs/design.md](https://github.com/melven/latex-chapmk/blob/main/docs/design.md).

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

- pdfLaTeX only. Tested in CI: TeX Live on Linux, MiKTeX on Linux and Windows; macOS not yet.
- Full builds (like latexmk, with a warning), most common first: BibTeX (biblatex with biber
  only), `cleveref`, hyperref without the `bookmark` package, `glossaries`, `minted`,
  `imakeidx`/`makeidx`, biblatex refsections, primitive `\mark`, an `eqparbox` tag used in
  several chapters whose width changes, and cases chapmk cannot verify.
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
  ([CONTRIBUTING.md](https://github.com/melven/latex-chapmk/blob/main/CONTRIBUTING.md)). Do not attach private documents.

## License

BSD-3-Clause ([LICENSE](https://github.com/melven/latex-chapmk/blob/main/LICENSE)).

Exceptions:
* hgbthesis as a test case in [tests/corpus/hgb/](https://github.com/melven/latex-chapmk/tree/main/tests/corpus/hgb/) - [CC BY 4.0](https://github.com/melven/latex-chapmk/blob/main/LICENSES/CC-BY-4.0.txt) - copyright Wilhelm Burger and the HagenbergThesis contributors, changes by Melven Roehrig-Zoellner
* pgf/TIKZ manual as a test case in [tests/corpus/pgfmanual/upstream/](https://github.com/melven/latex-chapmk/tree/main/tests/corpus/pgfmanual/upstream/) - [GFDL-1.2-only](https://github.com/melven/latex-chapmk/blob/main/LICENSES/GFDL-1.2-only.txt) OR [LPPL-1.3c](https://github.com/melven/latex-chapmk/blob/main/LICENSES/LPPL-1.3c.txt) - copyright Till Tantau and the PGF/TikZ contributors
