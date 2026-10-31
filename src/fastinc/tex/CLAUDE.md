# src/fastinc/tex: LaTeX packages

Rules (root CLAUDE.md): LaTeX2e with kernel hooks (expl3 allowed), internal prefix `\fastinc@`,
records and hooks only, no logic. The version in `\ProvidesPackage[... v<version> ...]` must
equal `fastinc.__version__` (checked by `tests/unit/test_tex_packages.py`).
**Keep this file in sync** with the packages.

| File | Loaded | Contents |
|---|---|---|
| `fastinc-ini.sty` | before `\documentclass`: format builds (`gensrc.format_source`), full and reference builds (`gensrc.full_mode_input`) | `\fastinc@kernelcount` (`\count10` at load time = kernel register boundary, S4); externalize neutralisation on hook `file/tikzlibraryexternal.code.tex/after` (`\tikzexternalize` swallows `[...]`, enable/disable `\relax`; §6.4.3); empty deferral table `\fastinc@deferred` (§6.3.3) |
| `fastinc.sty` | *M2*: at the split point of incremental runs (`gensrc.run_main`) | records of §6.4.2 / Appendix B |

The driver finds the packages through `TEXINPUTS` (`texdist.TeXLive.environment`).
