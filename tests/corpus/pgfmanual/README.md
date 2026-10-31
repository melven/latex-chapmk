# pgf/TikZ manual: stress-test corpus (third-party)

**Not written by the fastinc authors.** `upstream/` is an unmodified copy of the directory
`doc/generic/pgf` of the PGF/TikZ package, used only as a large real-world test document
(about 1300 pages, 123 `\include` chapters, heavy TikZ use).

| | |
|---|---|
| Source | <https://github.com/pgf-tikz/pgf>, tag `3.1.12`, commit `026504a0bb6cab7f4905b0e3f19734b91fb7da3b`, directory `doc/generic/pgf` |
| Why this version | matches the pgf version in TeX Live 2026 (`\pgfversion` 3.1.12) |
| Copyright | Till Tantau and the PGF/TikZ contributors (see the file headers and `upstream/CHANGELOG.md`) |
| License | dual: GNU Free Documentation License 1.2 **or** LaTeX Project Public License 1.3c, see `upstream/licenses/LICENSE` and the licence texts next to it |

The files in `upstream/` must stay unchanged. Adaptations needed by fastinc v1 are made at
test time on a copy by `adapt.py`, which writes an additional main file `fastinc-main.tex`:
the include structure is inlined into one main file, the index (`imakeidx`) is removed and
`bookmark` is loaded (see the docstring of `adapt.py`).

Use:
- `upstream/pgfmanual.tex` unchanged: full-mode builds (`fastinc build --full`, `fastinc check`);
- `fastinc-main.tex` after `adapt.py`: incremental builds and benchmarks.

Builds take minutes; tests on this corpus are marked `bench` (manual only).
