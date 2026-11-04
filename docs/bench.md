# Benchmarks ([design §8.4](design.md#84-benchmarks))

`python tests/bench/run.py --out DIR --chapters 20 --scale 3 --jobs 4` in the dev container,
4 cores. Corpus: thesis generator with 20 chapters, each 3× as long (319 pages, 22
`\include`s). latexmk with the same environment and a nomencl rule. Each edit starts from the
built state. The private document (`CHAPMK_BENCH_DOC`) was not available.

| scenario | latexmk | chapmk -j 1 | chapmk -j 4 |
|---|---|---|---|
| T16 cold | 64.2 s | 50.2 s (3 runs) | 30.3 s (9 runs, 3 batches) |
| T1 typo in ch10 | 16.5 s | 7.2 s (2 runs) | 7.5 s (2 runs) |
| T2 ch3 longer (pages shift) | 32.9 s | 37.1 s (5 runs) | 23.1 s (11 runs, 5 batches) |
| T4 new citation, renumbers | 37.7 s | 24.3 s (4 runs) | 17.3 s (7 runs, 4 batches) |

`--full` (plain fixpoint, like latexmk): 65.7 s.

## Breakdown

Per run (TeX, `\pdfelapsedtime` records): format load 0.17 s, rest of the preamble and
`\begin{document}` 0.35–0.45 s, glue (ToC, lists, nomenclature, bibliography) 1.0–1.2 s,
`\end{document}` 0.2–0.25 s, so about 1.9 s per run before any unit; a unit of this corpus
takes 0.6–1.0 s.

Per build (driver, wall): SyncTeX merge 1.3 s, PDF merge 0.3 s, preparation of run
directories 0.3–1.0 s, dirty computation 0.3–0.8 s, commit 0.1–0.6 s, analysis 0.2 s, biber
1.6–1.8 s when citations change. Cold builds add the format build (2.1 s).

T2 with `-j 4`, by iteration: ch3 alone (3.0 s); tail ch3..appB in 4 parallel runs (5 s);
the units importing moved labels in 4 parallel runs (5.4 s); two glue-only runs (2 × 2 s).

Optimised in M6: the SyncTeX merge mapped the path of every record (4.0 s → 1.3 s per build);
the canonical view is reused between batches.

## Remaining candidates

1. **Label prediction** (T2-type edits): predict the page numbers of labels in the units of a
   tail batch (shifted by the predicted page delta) and compile the importers in the same
   batch; verify afterwards. Saves one batch, about 5 s (20 %) of T2.
2. **Deferred glue writes** (§6.7.1): `\appendix` writes into the list files at the next
   shipout, whose position depends on which units a run compiles. Costs 1–2 glue-only runs
   (2–4 s) after runs with a different selection (T1: the second run; T2: the last two runs).
   Fix: flush pending writes at an excluded `\include` by a dummy shipout that the merge drops.
   Touches the output routine, so the risk is higher.
3. **Glue in every run** (1.0–1.2 s): inherent (`\includeonly` semantics); a parallel batch
   pays it per run.
4. Driver phases (about 3 s per build): small; SyncTeX parsing could be cached per run.
