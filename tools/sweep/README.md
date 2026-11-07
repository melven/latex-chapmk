# Corpus sweep (not for merging)

Tools to test chapmk on public documents. Kept on this branch so they survive the session;
the documents themselves are never committed, only their sources and the results.

- `find_corpora.py`: GitHub code search (queries in the file) for pdfLaTeX main files with
  at least three `\include`s; downloads each main file (raw.githubusercontent.com), filters
  XeLaTeX/LuaLaTeX signs, adds licence and stars (repository search). Output:
  `results/candidates.json`.
- `includify.py`: turns a document into one with top-level `\include`d chapters (inlines
  `\input` files, rewrites include wrappers such as KOMA's `\linclude`, splits at
  top-level `\chapter`).
- `sweep.py`: runs inside the dev image; per manifest entry: optional robustness variant
  (`--variant`: fontspec setup commented out, bookmark added, BibTeX replaced by biblatex),
  optional latexmk reference (`--latexmk`: latexmk vs `chapmk build --full`, §3.3
  comparison), cold `--check`, a typo in the middle unit and an incremental `--check`. One
  JSON line per document; work directories of failures are kept.
- `table.py manifest.json results.jsonl`: Markdown table.
- `run2.sh`, `run3.sh`: clone a manifest's repositories and run the sweep (`$SCRATCH`: scratch dir); `--prefilter` skips documents that do not compile with one plain pdflatex pass (second table: link and first error).

Results: `manifest1.json` (CTAN manuals and the 24 licensed theses with most stars),
`manifest2.json` (50 random documents of the larger search), `results/*.jsonl` and tables.
