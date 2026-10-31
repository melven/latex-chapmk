# src/fastinc/tex: LaTeX packages

Rules (root CLAUDE.md): LaTeX2e with kernel hooks (expl3 allowed), internal prefix `\fastinc@`,
records and hooks only, no logic. The version in `\ProvidesPackage[... v<version> ...]` must
equal `fastinc.__version__` (checked by `tests/unit/test_tex_packages.py`).
**Keep this file in sync** with the packages.

| File | Loaded | Contents |
|---|---|---|
| `fastinc-ini.sty` | before `\documentclass`: format builds (`gensrc.format_source`), full and reference builds (`gensrc.full_mode_input`) | `\fastinc@kernelcount` (`\count10` at load time = kernel register boundary, S4); externalize neutralisation on hook `file/tikzlibraryexternal.code.tex/after` (`\tikzexternalize` swallows `[...]`, enable/disable `\relax`; §6.4.3); empty deferral table `\fastinc@deferred` (§6.3.3) |
| `fastinc.sty` | at the split point of incremental runs (`gensrc.run_main`; driver macro `\fastinc@denynames` set before) | records of §6.4.2 / Appendix B, parsed by `records.py`. Segment tracking (`\fastinc@seg`, include counter `\fastinc@k`) on `include/before`, `include/after`, `include/excluded` and a `\@setckpt` wrapper. State vector = kernel checkpoint counters plus registers above `\fastinc@kernelcount`, minus deny list. `\fastinc@vec` is the expandable writer, with prefix `\fastinc@pfx`: `fastinc@b` = baseline, `all` = complete. Checkpoint = complete exit vector; restore after the kernel restore. `\jobname.frec`: `P` page map, `F` file/graphics attribution. `.nlo` segment markers. `\setcounter`/`\@stpelt`/`\pagenumbering` wrapped (`\protected`) for absolute sets. Bookmark levels at `enddocument`. Counter registers and reset lists (`\fastinc@counters`, from `\cl@@ckpt` and `\cl@<name>`) at `begindocument/end`. Layout flags (`\fastinc@layout`: twoside, openright). List-file markers: `\fastinc@ustart{U<k>}` as the first unit-aux statement and the `\fastinc@entry` handler write `\fastinc@lmark{U<k>}` / `{/<seg>}` (no-op) into the open list files (`\fastinc@listexts`, must equal `canon.LIST_SUFFIXES`) while the aux files are read at `\end{document}`. **No registers allocated** (they would enter the vector). |

The driver finds the packages through `TEXINPUTS` (`texdist.TeXLive.environment`).
