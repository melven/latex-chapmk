# fastinc — incremental, parallel pdfLaTeX builds

Implementation plan and specification. Working name: `fastinc` (rename freely).

---

## 0. Instructions for the implementing agent

1. Read the whole document before writing code.
2. Run milestone **M0 (spikes)** first. Every statement marked **[S#]** is an assumption verified by spike S#. Record each spike's result in `docs/spikes/S#.md` (what was tested, the minimal reproducer, the result). Then update this plan where reality differs, and commit that change separately.
3. Correctness beats speed. Every optimisation must be guarded by a verification, or by a fallback to a plain full build.
4. Do not modify user sources. All derived or generated material lives in the build directory.
5. Each milestone ends with green tests (§9). Add tests before or with features.
6. Keep the LaTeX package minimal: hooks and records only. All logic lives in the Python driver.

---

## 1. Goal

One command (`fastinc build main.tex`) replaces `latexmk -pdf -synctex=1`. It produces the same document (§3.3), but rebuilds faster after small edits by:

- precompiling the static preamble into a format file,
- recompiling only the `\include` units affected by an edit,
- compiling independent units in parallel,
- merging per-run PDFs and SyncTeX files into one `main.pdf` / `main.synctex.gz`, with working hyperref links, outline and page labels.

### Non-goals (v1)

- Engines other than pdfLaTeX.
- Units other than `\include` (no automatic splitting at `\chapter`).
- TikZ externalize. It is disabled by the driver (§6.4.3); re-enabling is a phase-2 option.
- Byte-identical PDFs.
- `glossaries`, `imakeidx`/`makeidx`, `minted`, `cleveref`. Detect these and fall back to full builds with a warning (§6.14).
- biblatex with `backend=bibtex` (or classic BibTeX). Only biber is supported; others fall back to full builds.
- PDF outline via hyperref's `.out` file, i.e. hyperref without the `bookmark` package. v1 supports the outline only through `bookmark`, which KOMA classes load automatically (S1). Without `bookmark`: fall back to full builds; the `.out` route is phase 2.

---

## 2. Document assumptions ("discipline")

The user's documents follow these rules. The driver relies on them and checks them where possible.

| # | Assumption | Check / consequence if violated |
|---|---|---|
| A1 | All macro definitions and settings are in the preamble. Unit bodies change only counters, labels, citations, list entries (ToC/LoF/…), nomenclature entries and bookmarks. | Lint (§6.8.4). A unit with a lint hit is marked *global*: its change dirties all successors. |
| A2 | Units are the files given to `\include` in the top-level body of the main file. | Analysis (§6.1). If `\begin{document}` is not in the main file, or an `\include` sits inside a group, only full builds are possible (fallback, §6.14). Nested `\include` is an error, as in LaTeX. |
| A3 | Body text of the main file between `\include`s ("glue": title page, ToC, lists, `\appendix`, nomenclature, bibliography, …) may change macros (e.g. `\appendix`, `\mainmatter`). | Glue is compiled in **every** run (standard `\includeonly` semantics). Any change to the main-file body dirties everything. |
| A4 | Footnotes are not split across a unit boundary. | Holds for the reference document (`\interfootnotelinepenalty=10000`). Acceptance tests guard it. |
| A5 | Every **compilation unit** starts with a chapter-level heading (`\chapter`, `\chapter*`, `\addchap`, `\part`, …). An `\include` file that does not (e.g. a sub-chapter include) joins the preceding include's compilation unit (§6.1). | S7: running heads of an include that continues a chapter are wrong in a partial run without its predecessor. Grouping makes A5 hold by construction; acceptance tests guard it. |

---

## 3. Requirements

### 3.1 Functional

- **F1** CLI compatible in spirit with `latexmk -pdf -synctex=1`: `main.pdf` and `main.synctex.gz` next to `main.tex` (or in `--out-dir`), exit code 0 on success.
- **F2** Incremental builds: after an edit, only affected units recompile, to a fixpoint (§6.9).
- **F3** Cold builds (no state) are correct and use parallelism after the first pass.
- **F4** SyncTeX forward and inverse search work across the merged PDF, including glue in `main.tex`.
- **F5** Internal hyperref links (`\ref`, `\autoref`, `\nameref`, `\hyperref[...]`, `\cite`, ToC entries), outline (bookmarks), page labels and document info work in the merged PDF.
- **F6** biblatex+biber and nomencl+makeindex are handled.
- **F7** Errors are reported with paths and line numbers mapped back to the user's sources. On error the previous `main.pdf` is kept.
- **F8** `fastinc watch`, equivalent to `latexmk -pvc`.
- **F9** `fastinc build --full` runs a plain reference build (latexmk-equivalent, same environment) for release and checks.
- **F10** `fastinc check` (or `fastinc build --check`) builds incrementally and with `--full`, then compares the results using §3.3. One call, exit code 1 and a per-item report on a difference. Available from M3 on, as a user-facing self-test.
- **F11** Coexistence with plain LaTeX builds in the same directory, without manual cleaning in between:
  - fastinc never reads build outputs from the source directory (shadow tree, §6.5).
  - In the output directory (default: next to `main.tex`), fastinc writes only `main.pdf`, `main.synctex.gz` and `main.log`. Each is replaced atomically, and the pdf and synctex file always come from the same build.
  - Everything else goes to the build directory.

### 3.2 Non-functional

- **N1** Incremental build after a typo-sized edit in one unit costs ≈ format load + glue + that unit + merge.
- **N2** Up to `-j N` parallel pdflatex processes (default: CPU count).
- **N3** Requirements: Python ≥ 3.10 and `pikepdf` (qpdf; wheels exist for Linux, macOS and Windows). LaTeX kernel ≥ 2023 (LaTeX hooks, `\ReadonlyShipoutCounter`). Optional for tests: poppler-utils (`pdftoppm`, `pdftotext`), `synctex` CLI.
  - Platforms: Linux, macOS and Windows with TeX Live (tier 1); Windows with MiKTeX (tier 2, §6.16).
- **N4** Deterministic environment: `SOURCE_DATE_EPOCH` and `FORCE_SOURCE_DATE=1`, so `\today` and the PDF dates are identical across runs.
  - The epoch is fixed **per canonical state** (M3): it is set at the cold build (`SOURCE_DATE_EPOCH` from the environment, else the build start time) and reused by all incremental runs and by the `--full` reference of `fastinc check`.
  - Reason: pages reused from earlier runs and new runs must show the same dates.

### 3.3 Acceptance criterion ("identical output")

The reference is `fastinc build --full`: plain latexmk on the unmodified sources, with only the externalize neutralisation injected (§6.4.3) and the same environment (N4). The merged result must match it in:

1. Page count; every page rasterised (`pdftoppm -r 150`) pixel-identical.
2. Extracted text per page (`pdftotext -layout`).
3. Page labels (one label string per page); outline (titles, levels, open state, resolved target page and coordinates); link annotations (rectangle, resolved target page and coordinates, or URI).
4. SyncTeX:
   - `synctex view` for sampled `file:line` positions (≥ 5 per unit and glue segment) returns the same page and h/v position;
   - `synctex edit` for sampled page positions returns the same `file:line`.

Byte identity is explicitly not required: merging changes object order, font subset naming and `/ID`.

---

## 4. Background: LaTeX mechanisms used

Short reference for the implementer. Details go into spike notes.

- **`\include{u}` / `\includeonly{...}`.** `\include` performs `\clearpage`, writes into its own `u.aux`, and at the end writes a counter checkpoint `\@setckpt{u}{...}` (all LaTeX counters registered via `\newcounter`) and does another `\clearpage`. With `\includeonly`, excluded units are not typeset; their `u.aux` (read at `\begin{document}` through `\@input` lines in `main.aux`) still provides labels, list entries and the checkpoint, which is restored when the excluded `\include` is reached. Main-file body text is always typeset.
- **Aux files** carry cross-references (`\newlabel`), list entries (`\@writefile{toc}{...}`), biblatex citation data (`\abx@aux@...`), package data (longtable `\LT@...`, eqparbox), and `\gdef\@abspage@last{N}`. At `\end{document}`, LaTeX re-reads all aux files and writes `.toc`, `.lof`, `.lot`, … from the `\@writefile` lines.
- **`bookmark` package.** Writes each outline entry as `\BKM@entry{id=N[,open][,dest={<hex>}][,color=…][,flags=…][,srcline={L}]}{<hex title>}` with `\immediate\write\@mainaux`, i.e. into the **main aux**. Level and parent are not written; they live in run-internal macros `\BKM@<id>` = `{parent}{level}{children}`. It affects only the PDF outline, not typesetting (S6).
- **Format files.** `mylatexformat` dumps the TeX state after a partial preamble into a `.fmt` file. Loading it replaces processing that preamble part. Open write streams cannot be dumped; mylatexformat collects `\openout` calls made during the dump and replays them at runtime, with `\jobname` expanded then (S1).
- **LaTeX hooks** (kernel ≥ 2020-10):
  - `include/before`, `include/end`, `include/after`, `include/excluded` [S3],
  - `file/before`, `file/after` (TeX input files),
  - `shipout/before` with `\ReadonlyShipoutCounter`.
- **pdfTeX named destinations.** hyperref uses named destinations (`\pdfdest name{...}`) collected in the catalog's `/Names /Dests` name tree; links reference names. If a name is referenced but not defined in a run, pdfTeX logs `pdfTeX warning (dest): name{X} has been referenced but does not exist, replaced by a fixed one` and creates a dummy destination. [S6]
- **SyncTeX file** (gzip text, grammar in `synctex_parser.c`):
  - header with `Input:<tag>:<path>` lines (more `Input:` lines may appear mid-file),
  - per-sheet blocks `{<sheet>` … `}<sheet>` containing records that reference input tags and line numbers,
  - postamble with counts and offsets. [S10]

---

## 5. Architecture

```
                 fastinc (Python driver)
 ┌───────────────────────────────────────────────────────────────┐
 │ analysis → format → scheduler/fixpoint → runs (parallel)       │
 │              │            │                 │                 │
 │              │            ├─ aux linker ◄───┤  (aux, sidecars)│
 │              │            ├─ biber / makeindex                 │
 │              │            └─ dependency model                  │
 │              ▼                                                 │
 │          canonical state (.fastinc/canon)                      │
 │              ▼                                                 │
 │          merge: PDF (pikepdf) + SyncTeX → main.pdf / .synctex.gz │
 └───────────────────────────────────────────────────────────────┘
        LaTeX side: fastinc-ini.sty (format/reference), fastinc.sty (runtime)
```

**Data flow of one build:**

1. Analyse the sources.
2. Rebuild the format if needed.
3. Compute the dirty set.
4. Prepare the run directories from the canonical state.
5. Run pdflatex jobs in parallel, each with `\includeonly{selection}`.
6. Commit the results to the canonical state.
7. Run the aux linker, biber and makeindex.
8. Re-evaluate the dirty set; loop to a fixpoint.
9. Merge.

---

## 6. Detailed design

### 6.1 Project analysis

Input: the main file (CLI argument or `fastinc.toml`).

1. **Locate the preamble:** lines `1 .. b-1`, where line `b` contains `\begin{document}`. Comments must be respected (`%` not preceded by `\`). Lines read via `\input` in the preamble are inlined for split detection only.
2. **Split point `s`** (first line not dumped into the format): the first preamble line matching the deny list (§6.3.2), or a config override `format.split_before = "<regex>"`. If the match lies inside a top-level command or group spanning several lines (e.g. `\ifdraft{` … `}`), set `s` to the line where that command starts (brace-depth tracking, S1). If `s` falls inside an `\input`ed preamble file, set `s` to the line of that `\input`.
3. **Segments** of the main body: tokenise top-level `\include{...}` occurrences. An `\include` in the preamble is not a unit: LaTeX processes it like `\input`, so it counts as a preamble input. Units `U1..Un` are in document order; glue segments `G0..Gn` (possibly empty) lie between them. Unit ids are the `\include` arguments (e.g. `chapters/intro`). An argument that is absolute or contains `..` is an error: its aux would be written outside the run directory, which TeX Live refuses (`openout_any = p`).
4. **Fingerprints** (sha256): `pre` (lines `1..s-1` plus inlined files), `post` (lines `s..b-1`), `body` (main-file text from `b` to end, excluding nothing).
5. **Compilation units** (A5, S7): group consecutive includes. An include whose first command (comments and blank lines skipped) is a chapter-level heading starts a new group; any other include joins the preceding group, together with the glue between them.
   - Heading list: `\chapter`, `\chapter*`, `\addchap`, `\addchap*`, `\part`, `\part*`, `\addpart`, `\addpart*`, plus config `[units] heading`.
   - If no include starts with one of these (classes without `\chapter`, e.g. `ltxdoc` for the pgf manual), `\section`, `\section*`, `\addsec` and `\addsec*` also count. If the first include of the document is not headed, it forms its own group and a warning is printed. The scheduler (§6.9) selects whole compilation units; segment ids (`U<k>`, `G<k>`) and all records stay per include.
6. **Unsupported-package detection** in the preamble → full-build mode (§6.14).

### 6.2 Generated sources, line-number preservation

All generated files keep the user's line numbers, so errors and SyncTeX map back by a path substitution only.

- **`.fastinc/fmt/pre.tex`** (format source):
  - `\RequirePackage{fastinc-ini}` prepended to line 1 (same line);
  - lines `1..s-1` verbatim;
  - then `\endofdump` [S1].
- **`.fastinc/runs/<r>/main.tex`** (per-run main), a copy of the user's main file with:
  - lines `1..s-1` replaced by empty lines;
  - line `s` prefixed (same line) with `\csname endofdump\endcsname\usepackage{fastinc}\includeonly{<selection>}`;
  - everything else verbatim.

  An empty selection is written as `\includeonly{}`, which means a glue-only run.
- **Path mapping table:** `runs/<r>/main.tex` → user `main.tex`, and the shadow-tree prefix `.fastinc/src/` → source directory (§6.5). Used for logs (§6.13) and SyncTeX (§6.12).

### 6.3 Format

#### 6.3.1 Build

```
pdflatex -ini -jobname=pre -output-directory=.fastinc/fmt "&pdflatex" mylatexformat.ltx .fastinc/fmt/pre.tex
```

- Rebuild when `pre`, the TeX Live version string, or the `fastinc-ini.sty` version changes.
- The class options are part of `pre` (the `draft` option freezes `\ifdraft`).
- Run usage: `TEXFORMATS=.fastinc/fmt:` and `-fmt=pre`. An absolute `-fmt=` path breaks `-recorder` (S1).

**Verified by S1** (`docs/spikes/S1.md`):
- At runtime, mylatexformat skips the main file line by line up to the first line containing `\endofdump`, `\csname endofdump\endcsname` or `\begin{document}`, then executes that whole line.
- The reference preamble dumps cleanly up to the externalize block, including `hyperref` and `biblatex`.
- Output is raster-, text- and SyncTeX-identical to a plain build.

#### 6.3.2 Deny list (split before the first match)

| Pattern | Reason |
|---|---|
| `\tikzexternalize` | Neutralised anyway; keeps the format independent of externalize. |
| `\makeindex`, `\makeglossaries`, `\usepackage{minted}` | Unsupported in v1 → full-build mode. |
| Config additions | User override. |

#### 6.3.3 Deferral (`fastinc-ini.sty`, format mode only)

`\openout` calls during the dump (e.g. `\makenomenclature`) need no handling: mylatexformat replays them at runtime (S1). The deferral table in `fastinc-ini.sty` is kept, empty, as a contingency for state that is opened or frozen by other means.

### 6.4 LaTeX packages

#### 6.4.1 `fastinc-ini.sty` (loaded before `\documentclass` in format builds and in the `--full` reference build)

1. Externalize neutralisation (§6.4.3).
2. Format mode only: the deferral table (§6.3.3; empty in v1).

#### 6.4.2 `fastinc.sty` (runtime, loaded at the split point)

Requirements:

1. **Segment tracking.** The variable `\fastinc@seg` holds the current segment id:
   - `G0` at `\begin{document}`;
   - `U<k>` at `include/before` (after the initial `\clearpage`, unit aux open; S3);
   - `G<k>` at `include/after` (after the final `\clearpage`, which ships deferred float pages; S3);
   - excluded unit: `U<k>` in the `\@setckpt` wrapper (see 2), `G<k>` at `include/excluded`. No pages are produced in between.
2. **State records.**
   - The *state vector* (S4) is:
     - the LaTeX counters in the kernel checkpoint list (`\cl@@ckpt`),
     - plus all `\count` registers allocated **after the kernel**, i.e. with an index above `\count10` at `\documentclass` (recorded by `fastinc-ini.sty`). Allocation is linear in `\count10`, with a jump to 266 when the classic range is exhausted.
     - minus a deny list of **run-local** registers, which number objects created in the current run: `Hy@abspage`, `BKM@id`, plus config `[state] ignore`.
     Kernel registers are scratch, absolute (shipout counters) or float-box insert counts; they are neither compared nor restored. Package scratch registers need no deny list: after the restore (3) they equal the full run (S4). The number↔name map comes from the allocation lines `\<name>=\count<n>` in the format and run logs. The deny list is re-evaluated against real documents (`fastinc check` on the benchmark document); a run-local register missing from it breaks the run (fallback) or shows up in acceptance tests.
   - At `\begin{document}` (end of the `AtBeginDocument` hooks), write a baseline `\fastinc@base{...}` to the main aux (`\immediate\write\@mainaux`), as a sparse vector `n=v,...`.
   - At each segment start, write `\fastinc@entry{<seg>}{<sparse vector vs base>}` to the main aux. This happens in every run, for selected and excluded units alike. For excluded units it is written **before** their checkpoints are restored. `include/excluded` runs after the kernel restore (S3), so the entry is recorded by wrapping `\@setckpt` (an aux handler): `\cp@<unit>` becomes `<record entry><original checkpoint>`. A unit without a checkpoint (never compiled) records no entry; it is dirty anyway (§6.9.1 f).
   - At each unit end, **after** the final `\clearpage` of `\include` (`include/after`, while the unit aux is still open [S3]), write `\fastinc@ckpt{U<k>}{<complete state vector: n=v,...>}` to the unit aux. Not at `include/end`: that hook runs before the final `\clearpage`, so the page counter and other changes made by the last shipouts would be missing.
     - **Complete vector, not only the registers changed within the unit (M2):** the exclusion itself can change registers. For example, calc's `\setcounter` uses the scratch register `\calc@Acount` during the kernel checkpoint restore. With the complete vector the restore undoes this; the per-unit delta for prediction is exit minus entry.
   - At each glue end, write `\fastinc@gexit{<seg>}{...}` to the main aux: at `include/before` or in the `\@setckpt` wrapper of the following unit, and at `\end{document}` for the last glue.
   - Absolute assignments: for each segment, record the set of registers assigned absolutely (hooks on `\setcounter`, counter resets via `\@stpelt`, `\pagenumbering`) as `\fastinc@abs{<seg>}{n,n,...}`, written to the unit aux for units and to the main aux for glue. Used for prediction only (§6.9.3), so missing cases only cost speed.
3. **Restore.** Reading `\fastinc@ckpt` from the unit aux stores the vector. The `\@setckpt{<unit>}` line read next in the same unit aux takes it over for `<unit>`. In the `\@setckpt` wrapper, after LaTeX's own checkpoint restore, the stored post-kernel registers (minus the deny list) are assigned globally. Loop indices must be macros, not registers. Without this restore, real state is lost (e.g. `Hy@linkcounter`, biblatex citation order, `LT@tables`, pgf picture serials) and pages differ; with it, all partial-run pages equal the full run (S4).
4. **Page map.** At `shipout/before`, `\immediate\write` to the records file `\jobname.frec`: `P <\ReadonlyShipoutCounter> <seg> <\the\c@page> <\thepage expanded via \protected@edef>`. One records file for page map and file attribution saves a write stream (TeX has 16).
5. **Segment markers in shared streams.** The only shared stream is `.nlo` (`\@nomenclaturefile`); outline entries go to the aux files (`bookmark`, §4). At every segment change, write the line `%fastinc-seg <seg>` into the stream, using a delayed `\write`, like nomencl's own `\protected@write` (S2b). This lets the driver attribute entries to segments.
6. **File attribution.** On `file/before`, `\immediate\write` to `\jobname.frec`: `F <seg> <\CurrentFilePathUsed/\CurrentFileUsed>`. Graphics: wrap `\Gin@setfile{type}{ext}{file}` (#3 is the resolved file name; S3) and write `F <seg> <file>`.
7. **Aux handlers.** Define `\fastinc@base`, `\fastinc@entry`, `\fastinc@gexit`, `\fastinc@abs`, `\fastinc@unit`, `\fastinc@bkmlevels` as no-ops, and `\fastinc@ckpt` as store (aux is read at begin and end document). `\providecommand` lines for all of them are written to the main aux.
   - **Implementation rules (M2):**
     - fastinc.sty allocates no registers, because they would enter the state vector; bookkeeping uses global macros.
     - The include counter is advanced on every `\include` (`include/before` or the `\@setckpt` wrapper or `include/excluded`).
     - Driver parameters (`\fastinc@denynames`) are defined before `\usepackage{fastinc}` in the run main.
8. **Externalize neutralisation** (§6.4.3), repeated idempotently.
9. **Bookmark levels.** At `enddocument`, write `\fastinc@bkmlevels{<id>=<level>,...}` to the main aux, read from bookmark's `\BKM@<id>` macros (S6).
10. **Deferred commands:** run the entries of the deferral table (§6.3.3; empty in v1).

#### 6.4.3 Externalize neutralisation

Install a file hook for `file/tikzlibraryexternal.code.tex/after` (the older name `file/after/<file>` is deprecated) [S3]. After the library loads, redefine:

- `\tikzexternalize` → swallow an optional argument, then do nothing;
- `\tikzexternalenable` and `\tikzexternaldisable` → `\relax`.

The user's `\todo` wrapper keeps working.

### 6.5 Runs

**Command:**

```
pdflatex -fmt=<fmt> -interaction=nonstopmode -halt-on-error -file-line-error \
         -synctex=1 -recorder -output-directory=.fastinc/runs/<r> -jobname=<job> \
         fastinc-run.tex
```

The run main has the fixed name `fastinc-run.tex` and is found via `TEXINPUTS` (run directory first). TeX reads the command line with the catcodes of the format, where e.g. the `underscore` package makes `_` active; a path on the command line containing `_` would abort the run (M2).

- The working directory is the **shadow tree** `.fastinc/src/`, so relative `\include`, `\input` and `\graphicspath` resolve as usual, and stale build files in the user's source directory (left over from manual builds) can never be read.
  - **Contents:** a mirror of the source tree made of symlinks to regular files. Excluded:
    - the build directory and `.git/`;
    - the LaTeX outputs of the main job: `<job><suffix>` for known output suffixes (`.aux`, `.toc`, `.log`, `.bbl`, `.synctex.gz`, `.pdf`, …; `shadow.BUILD_OUTPUT_SUFFIXES`), but not other `<job>.*` files, which may be sources (`pgfmanual.cfg`);
    - `<unit>.aux` of the units.
  - **Refresh:** once per build, before the runs. Parallel runs share it read-only.
  - **Path mapping:** shadow paths map to source paths by prefix substitution, for logs (§6.13) and SyncTeX (§6.12). SyncTeX records absolute, unresolved paths of the form `<cwd>/./<relative>`. Replace only the `<cwd>` prefix and keep the `/./`: `synctex view` matches relative file names by it (S10).
  - **Platforms:** where symlinks are unavailable (Windows without the privilege), use hardlinks, else copies [M7].
  - **Limitation (accepted in v1):** relative paths that leave the source tree (`\input{../x}`) do not resolve. Absolute paths work.
- Environment: N4 and `max_print_line=10000` (`TEXMF_OUTPUT_DIRECTORY` is not needed, S2).

**Run directory preparation:**

1. Copy the canonical `main.aux` and all unit aux files, preserving subdirectories.
2. Copy the derived files `.toc .lof .lot .loalg .lol .tdo .bbl .nls`.
3. Create the subdirectories for `\include` paths.

**Verified by S2** (`docs/spikes/S2.md`):
- The output directory is read first; the working directory is a fallback, so without the shadow tree a file missing from the run directory would be read stale from the source directory.
- The shadow tree works: `\include` subdirectories, `\graphicspath`, graphics and `.bib` through symlinks, SyncTeX.
- `\include` subdirectories must exist in the run directory.

**Outputs per run:** `<job>.pdf`, `.synctex.gz`, `.log`, `.fls`, `.aux`, unit aux files, `.frec`, `.nlo`, `.bcf`.

A run with selection *S* compiles the glue plus the units in *S*. A **full run** has *S* = all units. A **glue-only run** has *S* = ∅.

### 6.6 Canonical state and commit

`.fastinc/canon/` holds:

- the committed aux of each unit;
- the canonical `main.aux` and derived files;
- `main.bcf` and `main.bbl`;
- `main.nlo` and `main.nls`;
- bookmark records (`\BKM@entry` lines and `\fastinc@bkmlevels`, in the main-aux slices);
- `state.json`.

Per segment, `state.json` stores:
- the source fingerprint (hashes of attributed files),
- the observed entry vector and the exit checkpoint,
- the absolute-assignment set,
- the imported-key values at compile time,
- the artifact pointer `{run dir, PDF page indices, sheet numbers}`,
- the last compile time.

**Commit after a run with selection *S*:**

1. Each unit in *S*: take its aux, its pages (page map), its **main-aux slice**, and its per-segment `.nlo` entries (by markers). Its bookmark records are part of its aux.
   - The main-aux slice is the set of lines written to the main aux while the unit was the current segment, e.g. `\abx@aux@cite` (S5). Slices are delimited by the immediate `\fastinc@entry` records.
   - The canonical `main.aux` is assembled from the glue slices and the committed unit slices, in document order.
2. Glue: commit the glue artifacts from the run that §6.9 designates.
3. Store the observed entry vectors of **all** segments from this run, tagged with the run's input snapshot id.
4. Unreferenced run directories are garbage-collected after a successful merge (`--keep-runs` disables this).

**Implemented in M3** (`incremental.py`, `state.py`):
- **Cold build:** one run with all units, format and fastinc.sty, to the fixpoint (`fullbuild.converge`). Its aux, derived and `.bcf`/`.nlo` files become `canon/`. `state.json` records:
  - per segment the run and page indices;
  - per segment the source files attributed by the `F` records, with sha256;
  - global inputs: source files in the `.fls` attributed to no segment, plus the `.bcf` data sources.
- **Incremental step:** the dirty compilation units (attributed files changed) are compiled in one run from `canon/`. They are accepted only if the unit aux, the unit's main-aux slice and its nomenclature entries equal the canonical ones. The comparison ignores structural lines (`\relax`, `\providecommand`), which packages write once per run into whichever aux comes first, and replaces bookmark ids by levels (run-local, S6).
  - Then glue and all other units are still valid: only the unit's pages and files are committed.
  - Otherwise: cold build with the reason. M4 replaces this with the dependency model and the fixpoint.
- **Cold-build triggers:** no state, format stamp, main-file fingerprints, include list, a glue segment's attributed files, or global inputs changed.

### 6.7 Aux linker and aux classification

#### 6.7.1 Derived list files

Derived list files (`.toc`, `.lof`, …) are **written by TeX**, not by a Python linker (M3).
- A Python linker was tried and is not byte-identical: when writing, TeX expands content (`\protected@file@percent` → `%`), and aux macros such as `\babel@aux` add entries.
- Every run reads all aux files at `\end{document}` (its new ones and the canonical ones of excluded units) and writes complete list files.
- In M3 the list files stay canonical (verification). Since M4 every run's list files become canonical; the glue compiled in a later run reads them.
- **Deferred glue writes (M4 finding):** a non-immediate write of the glue (e.g. `\appendix` writes `\def\@chapapp{…}` to `.toc`/`.lof`/…) is flushed at the next shipout. In a full run that is the first page of the next unit, so the line follows that unit's entries; when that unit is excluded, it follows a later unit's entries. The list files then differ in the position of such lines. Consequence: right after a run that compiled such a unit, a run without it changes the list files and costs one glue-only run (T1 checks the steady state). Candidate fix (later): flush pending writes at an excluded `\include` with a dummy shipout that the merge drops.

#### 6.7.2 Line classification

Aux files are parsed as brace-balanced statements, not lines: `\@setckpt` and `\LT@…` records span several lines (S8).

| Aux line | File | Class |
|---|---|---|
| `\newlabel{k}{...}` | unit / main | export `k` (value = whole argument) |
| `\@writefile{ext}{...}` | unit / main | list contribution. Main-aux ones come from glue; delayed glue writes (e.g. `\appendix`) may be flushed inside a unit slice (S8) and keep the glue run's position. |
| `\@setckpt{u}{...}`, `\fastinc@ckpt{u}{...}` | unit | exit state |
| `\fastinc@entry`, `\fastinc@gexit`, `\fastinc@abs`, `\fastinc@base` | main | state records; `\fastinc@entry` also delimits the main-aux slices |
| `\abx@aux@cite{n}{key}`, `\abx@aux@segm{n}{n}{key}` | main, unit slice | citation (set and order), one line per key per citation command (S5) |
| `\abx@aux@backref{i}{key}{…}` | main, unit slice | unit content (citing page; read by the bibliography in the glue) |
| `\abx@aux@category{c}{key}` and other `\abx@aux@*` in a unit slice | main, unit slice | unit content (written at citation time, M4) |
| `\abx@aux@refcontext`, `\abx@aux@defaultrefcontext{n}{key}{…}`, `\abx@aux@number{i}{key}{…}{n}` (`defernumbers`), other keyed `\abx@aux@*` outside unit slices | main | biblatex data, merged per key (without the run-local `instcount` argument `i`); part of the key's citation value |
| `\abx@aux@read@bbl@mdfivesum`, `\abx@aux@read@bblrerun` | main, end | ignored (bookkeeping) |
| `\gdef\LT@<roman>{\LT@entry…}` (longtable) | unit | *self* |
| `\pgfsyspdfmark{pgfidN}{x}{y}` (pgf `remember picture`, todonotes) | main, unit slice | *self*, keyed by `pgfidN` |
| `\expandafter\gdef\csname eqp@(this\|next\|minwd\|maxwd)@<tag>\endcsname{…}` (eqparbox) | main, end of document | *self* per tag. Written only for tags typeset in the run, so they are merged per tag from the latest run that wrote the tag. Owner = units of that run. |
| `\global\csname @altsecnumformattrue\endcsname` (KOMA autodot) | main, end of document | OR-aggregate over the typeset segments; attributed to the run's included units; *global* |
| `\BKM@entry{...}{...}` (bookmark) | main, unit slice | outline record: merge only (§6.11); a change dirties nothing |
| `\fastinc@bkmlevels{id=level,...}` | main, end | outline levels (§6.4.2); merge only |
| `\babel@aux{...}`, `\@nameuse{bbl@beforestart}`, `` \catcode `"\active `` | main, header | structural (language state; A1 lint covers `\selectlanguage`) |
| `\gdef\@abspage@last{N}` | main, end | rewritten to the merged page count |
| `\relax`, `\@input{u.aux}`, `\providecommand…` | header / glue | structural |
| anything else | | **global**: a change dirties all units and glue; print a warning naming the macro, so the table can be extended |

**Canonical main aux** (S8). Start from the main aux of the run that committed the glue, then:
1. For each unit, replace the unit-content kinds (`\BKM@entry`, `\abx@aux@cite/segm`, `\abx@aux@backref`, other biblatex data, `\pgfsyspdfmark`; `aux.UNIT_CONTENT`) in its slice with those from the unit's committed slice.
2. Merge the end-of-document aggregates as in the table.

### 6.8 Dependency model

#### 6.8.1 Inputs of a unit *u*

1. **Format and preamble:** `pre`, `post`. A change dirties everything.
2. **Main body:** `body`. A change dirties everything (A3).
3. **Own sources:** files attributed to *u* via `.ffl`, plus graphics. Files from `.fls` under the source tree that are attributed to no segment are global inputs (a change dirties everything). Not tracked by hash: files in the TeX distribution (covered by the TeX Live version string and the format fingerprint, §6.3.1) and files generated in the build directory (aux, derived lists, `.bbl`, `.nls`; covered by the dependency model).
4. **Entry state:** the observed entry vector (§6.9 defines validity).
5. **Imports:** label keys and cite keys used by *u*. These are determined by a **text scan** of *u*'s attributed TeX files for every known key K: regex `(?<=[{,\[\s])K(?=[},\]\s])`. Comments count too, so this is a safe over-approximation. A label value changes when the whole `\newlabel` argument changes (number, page, title, anchor). A cite value is the key's `.bbl` entry block plus its position in the `.bbl`.
6. **Self aux:** the class-*self* lines of *u*'s aux at compile start must equal those after compile (standard rerun rule).
7. **Derived files read by *u*:** recorded via `.ffl` (e.g. a unit that contains `\printbibliography`).

#### 6.8.2 Inputs of the glue

Glue is compiled in every run, so its pages are valid only if they were produced under the final canonical state. Its inputs:
- `body`,
- derived files read by glue segments (from `.ffl`),
- the entry vectors of the glue segments,
- imports by text scan of the main file and glue-attributed files.

#### 6.8.3 Outputs that propagate

- Exit state of a unit → successors' entries.
- Exports → importers.
- List contributions → derived files → readers (usually glue).
- Citations → `.bcf` → biber → `.bbl` → importers.
- Nomenclature entries → `.nlo` → makeindex → `.nls` → readers.
- Bookmark records → outline, used only by the merge; no TeX dependency.

#### 6.8.4 Lint (A1)

Scan unit sources (comments stripped) for occurrences of the commands below. There are two lists.

**Local-effect commands.** These are a hit only outside an explicit group:

```
\def \edef \let \newcommand \renewcommand \providecommand \DeclareRobustCommand
\NewDocumentCommand \RenewDocumentCommand \NewCommandCopy \newenvironment
\renewenvironment \setlength \addtolength \captionsetup \sisetup \lstset \tikzset
\definecolor \makeatletter \catcode \ExplSyntaxOn
```

**Global-effect commands.** These are always a hit, grouped or not:

```
\gdef \xdef \global \newcounter \newlength \newcount \newdimen \newskip \newtoks
\newtheorem \counterwithin \counterwithout \pagenumbering \pagestyle \appendix
\frontmatter \mainmatter \backmatter \selectlanguage \hypersetup \KOMAoptions
\usetikzlibrary \DeclareSIUnit \DeclareMathOperator
```

- A command from the local list prefixed by `\global` counts as global.
- **Explicit group:** an environment (`\begin{...}` … `\end{...}`), `\begingroup` … `\endgroup`, or a brace group whose `{` is not a macro argument. A `{` directly after a control word, `}` or `]` counts as an argument, because arguments need not form a group (e.g. `\ifdraft{...}{...}`), so it does not exempt.
- **Warning text:** for a local command, suggest wrapping it in a group or environment; for a global command, suggest moving it to the preamble.

- A hit gives a warning with `file:line`, and the unit is marked *global*.
  - **M4:** state changed by a global unit (e.g. `\parskip`) is not in the checkpoints, so later units and later glue see it only in a run that compiles the global unit. Therefore a global unit is compiled **in every run**, and when it is dirty itself, all later units are compiled in the same run. (The earlier rule "when recompiled, all successors are dirty" would compile them in a later run without the global unit, i.e. without its state.)
- Config `lint.allow = [...]` lists exceptions.
- The exemption is a heuristic. The acceptance tests guard it (T18 and a grouped variant).

### 6.9 Scheduling and fixpoint

#### 6.9.1 Dirty set

A unit *u* is dirty if any of these holds:

- (a) its source fingerprint changed;
- (b) an import value changed;
- (c) its self aux is unstable;
- (d) its observed entry vector differs from the current *expected* entry vector;
- (e) a predecessor marked *global* was recompiled;
- (f) it has never been compiled.

The *expected* entry vector comes from the latest run whose input snapshot equals the current canonical state, or from prediction (§6.9.3).

#### 6.9.2 Basic loop (milestone M4)

```
if format/pre/post/body/unit-list/global-input changed or no state: dirty = all
loop i = 1..K (K = 6):
    if dirty == ∅ and glue valid: break
    if dirty == ∅: run glue-only (S = ∅); commit; recompute dirty (entries observed); continue
    partition dirty into ≤ N runs:
        - if a dirty unit's entry depends on another dirty unit's exit (it lies after it)
          and prediction is disabled → put all dirty units from the first such unit on
          into ONE run ("tail run"); remaining independent dirty units in other runs
        - else contiguous groups balanced by last compile time
    run batch in parallel; commit
    aux linker; biber if citations/bib changed (§6.10); makeindex if .nlo changed
    recompute dirty:
        - (a)(b)(c)(e) driver-side
        - (d): expected entries are known exactly only from a run that saw the
          current canonical state for all predecessors; otherwise mark a unit dirty if any
          predecessor's exit state or any derived file read by preceding glue changed
    glue valid ⇔ the run that produced the committed glue pages had the same glue inputs
                 (§6.8.2) as the current canonical state
if not converged: full run (S = all) once; if still not converged: error with diagnostics
```

Cheap common case: a typo edit means one run, the unit's exit, exports and contributions are unchanged, the glue stays valid → merge.

**Implemented in M4** (`incremental.Fixpoint`, `canon.py`, `deps.py`):
- One run per iteration: the dirty compilation units (all: no `\includeonly`; none: glue only) plus the glue; at most 8 runs, then full mode (§6.14). A cold build is the same loop with all units dirty and an empty `canon/`. The loop ends when no unit is dirty and the glue is valid.
- Dirty rules after a run:
  - sources changed;
  - imports: keys found by the text scan whose value differs from the one at compile start (label: whole `\newlabel` argument; citation: `.bbl` block and position plus keyed biblatex aux data such as `\abx@aux@number`);
  - self data (unit-aux and slice statements of class *self*) differs before/after the compile;
  - entry state: a unit not compiled in the run whose observed entry vector differs from the one it was compiled with. Tail rule: it and **all later units** are compiled in the next run (no prediction until M5);
  - eqparbox widths changed: the units of the run; aggregate (KOMA autodot) or unclassified aux data changed: all units;
  - a list file changed for a unit that typesets lists (text scan for `\tableofcontents`, `\listof…`, `\printbibliography`, …, or a derived file in its `F` records).
- Glue validity: hash of the derived files, the values of keys imported by the main file and glue files, and the glue aux data (list typesetting data, eqparbox, aggregates, backrefs, unclassified, glue self data; keyed data order-insensitive) at the start of the run that produced the committed glue, compared with the current canonical state; glue sources changed → invalid (a glue-only run, no cold build).
- The run's input main aux omits the citations of excluded units: biblatex compares the previous citations with the current ones and would treat them as removed, which suppresses e.g. the `defernumbers` data (found on hgb).
- State that persists between builds: `pending` (dirty reasons) and `glue_pending` if a build stopped before the fixpoint (TeX error).
- Measured on the thesis corpus: cold build 3 runs; T2 (ch2 longer) 3 runs (ch2; tail ch2..appB; all importers of moved labels).

#### 6.9.3 Prediction for parallel recompilation of successors (milestone M5)

When a unit's exit state changes (e.g. its page count), successors would otherwise need a sequential tail run. Instead:

1. **Composition model** for a segment *g* with old entry *E*, old exit *X*, absolute set *A*, and new entry *E'*:
   `X'[r] = X[r]` for `r ∈ A`, otherwise `X[r] + (E'[r] − E[r])`.
   This holds for units (from `\fastinc@ckpt` / `\@setckpt`) and for glue (from `\fastinc@entry` / `\fastinc@gexit`).
2. **Predict:** starting from the first changed exit, propagate predicted entries and exits through all later segments.
3. **Write predictions:** rewrite the predicted exit checkpoints (`\@setckpt` values and `\fastinc@ckpt`) into the canonical aux of units that are not recompiled in this batch but lie before recompiled ones.
4. **Run** all dirty units in parallel.
5. **Verify** in document order: each recompiled unit's observed entry must equal its predicted entry, and every unit whose predicted exit was used must have an actual exit equal to the prediction. At the first mismatch, every later unit compiled in this batch is dirty again.
6. **Limit:** two consecutive mispredictions for the same unit → that iteration uses a tail run.

Known misprediction cases are harmless and only cost an iteration:
- page parity with `twoside, openright` (blank pages appear or disappear),
- reference-string width changes,
- ToC length changes.

#### 6.9.4 Cold build

1. Full run (*S* = all). It produces all aux files, checkpoints, a complete `.bcf`, and pages for all segments.
2. biber and makeindex.
3. Continue the loop. Typically all units with references are dirty (labels were undefined) → parallel batch. Entries are correct from the full run's checkpoints, so no prediction is needed.

Expected cost ≈ 1 full pass + (p − 1) parallel passes, instead of p full passes.

Phase 2: a speculative parallel first pass with composition (needs a model for "no aux yet").

### 6.10 External tools

**biber:**
- Run with cwd = shadow tree (§6.5): `biber --output-directory <build>/canon main`. Biber then reads `main.bcf` from `canon/` (the output directory is searched first) and resolves `.bib` paths relative to the working directory. Do not pass `--input-directory`: biber would then look for `main.bcf` only there.
- Trigger: the citation set or order changed, the `.bib` hash changed, or the `.bcf` structure changed.
- **`.bcf` patch** (S5: a partial run's `.bcf` lists only glue and included units; everything else in it is identical):
  - Per run, the `bcf:citekey` elements of each `bcf:section` correspond 1:1, in order, to the `\abx@aux@cite{<section>}{<key>}` lines of the main aux. The segment slices (§6.6) therefore attribute each element to a segment.
  - The canonical citekey list per section is the concatenation, in document order, of each segment's elements from the run that committed that segment. `order` is renumbered globally (one number per citation command); `intorder` and `nocite` are kept.
  - Verification: the element count per run must equal the `\abx@aux@cite` count, otherwise biber runs on the `.bcf` of a full run (fallback). Tests require the patched `.bcf` to be byte-identical to a full run's.
  - Biber never runs on an unpatched partial `.bcf`.
- After biber, diff the `.bbl` per `\entry{key}…\endentry` block (content and position) → changed cite values.

**makeindex (nomencl):**
- Canonical `main.nlo` = the concatenation of the per-segment `.nlo` entries in segment order.
- Run `makeindex main.nlo -s nomencl.ist -o main.nls`.
- Trigger: `.nlo` changed.

### 6.11 PDF merge (pikepdf)

Input: for each segment in document order, its committed artifact `(run PDF, page indices)`.

1. **Pages:** create a new PDF and append the pages in order (foreign object copy). Build the map `(run, page index) → merged page`, and also `(segment, offset in segment) → merged page`.
2. **Named destinations:**
   - From each source run, collect `/Root/Names/Dests` entries.
   - Keep a name only if its target page belongs to the pages taken from that run, and the name is not a dummy. Dummies are listed in the run log as `pdfTeX warning (dest): name{X} has been referenced but does not exist, replaced by a fixed one`; their target is `[<page 0> /Fit]` (S6). Values have the form `<< /D [<page> /XYZ x y null] >>`.
   - Remap the target page through the map.
   - Duplicate names: mirror pdfTeX, which keeps the first definition and ignores later ones (`pdfTeX warning (ext4): destination with the same identifier (name{X}) has been already used, duplicate ignored`). The merge keeps the definition from the first merged page in document order and drops later ones. Typical case: `page.N` names from title pages or restarted numbering. Since a partial run may lack the earlier definition, attribution is by merged page order, never by run. [S6] verifies that the full run produces the same winner.
   - Every name referenced by a link or the outline must resolve.
     - A name that no run defines gets pdfTeX's dummy destination (first page, `/Fit`), as in a plain build. Example: hgb, longtable caption in `\endfirsthead`.
     - A name defined only on pages that were not taken → error → fallback.
   - Write the merged name tree.
3. **Annotations:**
   - Links using named destinations (`/A <</S/GoTo/D (name)>>` or `/Dest (name)`) stay as they are.
   - Direct page-object destinations are remapped via the `(segment, offset)` map.
   - `/P` entries are set to the merged page.
4. **Outline:** built from the `\BKM@entry` records of the canonical main aux (segment slices in document order). Decode the hex fields: `dest` → name; the title → PDF string bytes (TeX octal escapes, typically UTF-16BE with BOM). The level of each entry comes from the same run's `\fastinc@bkmlevels`. The tree is rebuilt with bookmark's rule: the parent is the nearest previous entry with a lower level. `open`, `color` and `flags` come from the entry (S6).
   - Each outline item gets `/Dest (dest)` (named) with `/Parent`, `/First`, `/Last`, `/Next`, `/Prev` and `/Count` (open state and level-gap handling as `bookmark` does it).
   - The catalog `/PageMode` comes from the reference run.
5. **Page labels:** from the page map's `(value, \thepage text)` per page, infer the style: arabic → `/D`, roman → `/r`, Roman → `/R`, alph → `/a`, Alph → `/A`, otherwise a prefix-only label `/P`. Compress into a `/PageLabels` number tree. Compare against the reference in tests.
6. **Catalog and Info:** copy `/Info`, `/OpenAction` (remapped), `/PageMode`, `/PageLayout` and `/ViewerPreferences` from the run that produced `G0`. Do not copy `/Pages`, `/Names`, `/Outlines` or `/PageLabels` (built above).
7. **Output:** write to a temporary file and rename atomically to `main.pdf`.

Expected side effect: a larger file, because font subsets are duplicated per run. This is acceptable; `--full` produces the compact version.

### 6.12 SyncTeX merge

Verified by S10 (`docs/spikes/S10.md`).

1. Parse each source `main.synctex.gz`:
   - header (`Input:` lines, which may also occur mid-content; `Output`, `Magnification`, `Unit`, `X Offset`, `Y Offset`);
   - sheets `{n` … `}n`;
   - tagged records `<type><tag>,<line>:…` with types `[ ( h g k x $ v r`.
2. Build a global input table keyed by path.
   - Map `runs/<r>/main.tex` to the user's `main.tex`, and the shadow-tree cwd prefix to the source directory. Keep the `<cwd>/./<relative>` form.
   - Line numbers are unchanged (§6.2).
   - Rewrite the tags of all records.
3. Take only the sheets of the selected pages (page map) and renumber them to merged page numbers.
4. Write the file:
   - the header, copied from the runs; the values must be equal, otherwise error;
   - `!<n>` before every `{n`, every `}n` and the postamble, where `n` = bytes since the previous `!` line;
   - the postamble `Postamble:`, `Count:<records>`, `!<n>`, `Post scriptum:`;
   - then gzip.
5. Verify with the `synctex` CLI in tests: `view` for every source line with records, and `edit` at the resulting positions.

### 6.13 Logs and errors

- Print errors in `-file-line-error` form with mapped paths (`runs/<r>/main.tex` → `main.tex`).
- On a failing run:
  - commit nothing from that run;
  - keep the previous `main.pdf`;
  - exit code 1;
  - write `main.log` containing the failing run's log (paths mapped) for editors that parse it.
- On success, `main.log` concatenates the logs of the final runs, each with a header line.
- Warnings: undefined references and citations are reported only if they remain at the fixpoint.

### 6.14 Fallbacks to full mode

Full mode means plain sequential full runs to a fixpoint inside the build directory (like latexmk), with a SyncTeX file but without merging. Triggers:

- unsupported packages (§1 non-goals): detected statically in the preamble, and at runtime from the `.fls` of the format build **and** the run. Packages dumped into the format are not in the run's `.fls`, and classes may load packages, e.g. `bookmark` only at `\begin{document}`.
  - `hyperref` loaded without `bookmark` also counts.
  - Runtime reasons are persistent: the next builds go straight to full mode until the main file changes (`canon/full-only.json`);
- `\documentclass` not before the split line (e.g. on the `\begin{document}` line);
- format build failure;
- a merge error (missing destinations, inconsistent SyncTeX header);
- the fixpoint not reached (§6.9.2);
- missing records (e.g. a page without a page-map entry);
- `--full`.

Each trigger prints a one-line reason.

### 6.15 CLI and configuration

```
fastinc build [MAIN] [-j N] [--full] [--check] [--report FILE] [--build-dir DIR] [--out-dir DIR] [--keep-runs] [-v]
fastinc watch [MAIN] [same options]        # rebuild on change of any recorded input
fastinc check [MAIN]                       # = build --check: incremental vs --full, criterion §3.3
fastinc clean [MAIN]
fastinc graph [MAIN] [--format text|dot|json]   # compilation units and dependencies
```

**`fastinc graph`** shows the build structure from the analysis and the last state:
- the compilation units (§6.1) with their includes;
- glue segments;
- units marked *global* (lint hits);
- edges:
  - entry-state chain (exit → successor entry);
  - imports (label/cite key → exporting unit);
  - list contributions → derived files → reading segments (ToC, LoF, bibliography, nomenclature).

`--format dot` gives a Graphviz graph. The build report (`fastinc build --report json`) uses the same data and adds, per compiled unit, the dirty reason (§6.9.1 a–f).

`fastinc.toml` (optional):

```toml
main = "thesis.tex"
jobs = 0                       # 0 = CPU count
build_dir = ".fastinc"
[format]
split_before = []              # extra regexes
[lint]
allow = []                     # e.g. ["\\setlength"]
[units]
heading = []                   # extra chapter-level heading commands (A5)
[aux]
self = []                      # extra regexes of aux lines classified "self"
ignore = []
[state]
ignore = []                    # extra \count registers excluded from the state vector
```

### 6.16 Cross-platform

All TeX invocations go through a **distribution adapter** (`texdist.py`) with two implementations: `TeXLive` and `MiKTeX`. Driver logic must not hard-code engine flags or search behaviour.

| Topic | TeX Live (all OS) | MiKTeX | Driver rule |
|---|---|---|---|
| Format build and use | `-ini`, `-fmt=` | `--initialize`, `--undump=` (also `&name`) [S11] | Adapter |
| Output and aux directories | `-output-directory`, `TEXMF_OUTPUT_DIRECTORY` | `--output-directory`, `--aux-directory`; own search order [S11] | Adapter; S2 is repeated for MiKTeX |
| On-the-fly package install | n/a | may prompt or block parallel runs | Require "install missing packages: never/always" with no prompting; check at startup, otherwise abort with instructions |
| `SOURCE_DATE_EPOCH` / `FORCE_SOURCE_DATE` | supported | [S11] | If unsupported: no determinism guarantee; `check` uses a pinned date via a `\today` override in `fastinc-ini.sty` |
| mylatexformat, biber, makeindex, synctex | available | packages available [S11] | Startup check |

**OS rules:**
- **Paths:** use `pathlib` internally; always pass forward slashes to TeX; reject source paths with spaces under `\include` (TeX limitation) with a clear error.
- **SyncTeX paths:** normalise case and drive letters on Windows when mapping input tags.
- **Line endings:** generated files keep the source's line endings; read and write in binary mode, so line numbers are preserved.
- **Output replacement:** `os.replace` onto `main.pdf` fails on Windows while a viewer locks the file (e.g. Adobe Reader). Retry with backoff for 2 s, then write `main.fastinc.pdf` and warn. SumatraPDF does not lock.
- **Processes:** use `subprocess` only, no `fork`; the process pool must be spawn-safe.
- **Watch mode:** `watchdog` (cross-platform).
- **Performance on Windows:** process start-up and antivirus scanning of many small files are slower. Document the recommendation to exclude the build directory from on-access scanning.

**CI matrix:** Linux/TeX Live, macOS/TeX Live, Windows/TeX Live, Windows/MiKTeX. Scenario tests run on all four. Raster comparison needs poppler, installed via conda on Windows.

---

## 7. Repository layout

The module map with public APIs is in `src/fastinc/CLAUDE.md` and is kept current there.

```
pyproject.toml                 # console script: fastinc
src/fastinc/
  CLAUDE.md                    # module map for agents
  cli.py  config.py  errors.py
  texsource.py                 # TeX source scanning
  analysis.py                  # §6.1
  gensrc.py                    # §6.2
  layout.py  shadow.py         # build directory, shadow tree (§6.5)
  texdist.py  proc.py          # §6.16 adapter, subprocess helper
  fmt.py                       # §6.3
  fullbuild.py                 # §6.14 full mode
  publish.py  logs.py          # outputs (§6.16), logs (§6.13)
  synctex.py                   # SyncTeX file handling (§6.12; the merge follows in M3)
  check.py                     # §3.3 comparison
  runner.py  state.py  aux.py  deps.py  scheduler.py  tools.py  merge_pdf.py   # M2-M5
  tex/fastinc-ini.sty  tex/fastinc.sty  tex/CLAUDE.md
tests/
  unit/  slow/  acceptance/  scenarios/  bench/
  corpus/thesis/               # §8.1 (generated by generate.py)
  corpus/hgb/                  # second real-world preamble (anonymised)
  corpus/pgfmanual/            # pgf/TikZ manual, third-party stress test (upstream/ unmodified)
  corpus/minimal/              # spike reproducers S1-S10
docs/spikes/S1.md ... S10.md
```

## 8. Test strategy

### 8.1 Corpus

**`tests/corpus/thesis/`** — the user's real preamble is supplied as `preamble.tex`; the implementer inlines it into `main.tex` (it must stay in the main file, as in the user's projects). Generated content:

- **Main body:** title page, `\tableofcontents`, `\listoffigures`, `\listoftables`, list of algorithms (`loalg`), `\listoftodos`, `\printnomenclature`, `\mainmatter`, 6 chapters via `\include`, `\appendix` followed by 2 appendix chapters via `\include`, and `\printbibliography`.
- **Chapters** contain:
  - equations and theorems (counters per chapter), footnotes, `\section*`;
  - figures via `\pgfimage` (PDFs in `fig/`) and small tikzpictures;
  - subfigures, tables (booktabs, multirow, makecell, `longtable` over a page break);
  - siunitx with the custom units;
  - algorithms with `\COMMENT{...}` (eqparbox), listings;
  - `\nomenclature` entries with groups A–P;
  - citations to a synthetic `thesis.bib` (≥ 40 entries);
  - cross-chapter `\ref`, `\autoref`, `\nameref`, `\subsecref`, `\pageref`;
  - `\todo`;
  - a `\foreignlanguage{ngerman}{...}` passage.
- **Variants:** `twoside` + `openright` (the reference), and `oneside`.

**`tests/corpus/hgb/`**: a second real-world preamble (class `hgbthesis` from TeX Live), anonymised.
- What it tests: a class that loads biblatex itself, `underscore`, `tcolorbox`, `arydshln`, listings via the class's own environments, `\input` macro files in the preamble, a local theme file in the source directory.
- Body: four includes, one of them a sub-chapter include (compilation unit grouping, A5).

**`tests/corpus/pgfmanual/`**: the pgf/TikZ manual (third-party, see its README), about 1300 pages and 123 `\include` sections.
- `upstream/` is unmodified (pgf tag 3.1.12, which matches TeX Live 2026; FDL 1.2 / LPPL 1.3c).
- `adapt.py` writes `fastinc-main.tex` in a test copy: includes inlined into the main file (A2), index removed (non-goal), `bookmark` added.
- Stress test and benchmark only (marker `bench`).

**`tests/corpus/minimal/`**: tiny documents isolating each mechanism, used in spikes and unit tests.

### 8.2 Scenario tests

Each test starts from a built state, applies an edit, runs `fastinc build`, asserts §3.3 against `--full`, and asserts the expected set of compiled units (from the build report, `--report json`).

| ID | Edit | Expected recompiles |
|---|---|---|
| T1 | typo in ch3 (no layout change) | ch3 only; no glue-only run |
| T2 | add a paragraph to ch3 that changes its page count | ch3; then ch4..end (parallel with prediction, a tail run without); glue |
| T3 | rename a section in ch2 that ch5 references by `\nameref` | ch2, ch5, glue (ToC) |
| T4 | new citation in ch4 that renumbers the bibliography | ch4, biber, all citing units, glue |
| T5 | new label in ch6 referenced from ch1 | ch6, ch1 |
| T6 | new nomenclature entry in ch2 | ch2, makeindex, glue |
| T7 | longtable rows added in ch3 | ch3 (self rerun until stable) |
| T8 | algorithm comment width change | that unit (self) |
| T9 | new figure in ch2 | ch2, successors whose figure numbers are unaffected stay clean; glue (LoF) |
| T10 | ch1 page count changes by 1 (parity) | the misprediction path is exercised; output correct |
| T11 | move `\appendix` in main.tex | all |
| T12a | preamble edit after the split | all, no format rebuild |
| T12b | preamble edit before the split | format rebuild, all |
| T13 | add an `\include` | all |
| T14 | syntax error in ch4 | exit 1, previous PDF kept, error at `ch4.tex:<line>` |
| T15 | `\section*` in several units | no duplicate destination names beyond those of the `--full` run; every link resolves to the same target |
| T16 | cold build | §3.3; report wall time vs `--full` |
| T17 | SyncTeX round trip for every segment | §3.3 item 4 |
| T18 | `\setlength` in ch2 body | lint warning; ch2 is global; successors recompiled after ch2 changes |
| T18b | `\setlength` inside a `table` environment and inside `{...}` in ch2 | no lint hit; ch2 not global; §3.3 holds |
| T19 | stale `main.aux` and unit aux files in the source directory | ignored (shadow tree); §3.3 holds |
| T19b | alternate latexmk → fastinc → edit → latexmk → fastinc in one directory, no cleaning | both builds correct (fastinc: §3.3; latexmk: same as a latexmk build in a clean copy); SyncTeX matches the current pdf |
| T20 | ch3 split into `ch3.tex` (starts with `\chapter`) and `ch3b.tex` (continues with `\section`), edit in `ch3b` | one compilation unit {ch3, ch3b} recompiled; running heads identical to `--full` (§3.3) |

### 8.3 Unit tests

- Aux parser and classifier.
- Linker output equals the full-run `.toc`/`.lof`/`.lot`/`.loalg`/`.tdo`.
- `\BKM@entry` parser and outline builder (against the outline of full runs).
- Page-label inference.
- `.bbl` entry diff; `.bcf` patch.
- Composition model (including absolute sets).
- Text-scan import detection.
- SyncTeX parse and write round trip (identity for an unmodified file).
- PDF merge of two hand-made runs (destinations, dummy removal, links).

### 8.4 Benchmarks

`tests/bench/run.py` reports wall times for T1, T2, T4 and T16 against `latexmk` (same environment, externalize off) on the thesis corpus, with `-j 1` and `-j N`. Numbers go into `docs/bench.md`.

---

## 9. Milestones

### M0 — spikes, each with a minimal reproducer under `tests/corpus/minimal/` and a note under `docs/spikes/`

| Spike | Question |
|---|---|
| S1 | *Done.* mylatexformat with the thesis preamble split before `hyperref`: dump OK? Runtime skip semantics with the marker plus blank lines? SyncTeX OK? Can `hyperref` and `biblatex` go into the format? `\makenomenclature` deferral works? |
| S2 | *Done.* `-output-directory` read order (aux and derived files); shadow tree (§6.5): `\include` subdirectories, `\graphicspath`, symlinked graphics and `.bib`, SyncTeX paths; stale files in a plain source directory (documentation only); `TEXMF_OUTPUT_DIRECTORY`. S2b: write mode of nomencl's `.nlo` writes. |
| S3 | *Done.* Hook order: `include/before` relative to the initial `\clearpage`; pages from the final `\clearpage` before `include/after`; whether the unit aux is still open (`\@auxout` = `\@partaux`) at `include/after`, else where to write `\fastinc@ckpt`; existence and timing of `include/excluded` relative to the checkpoint restore; file hook for TikZ libraries; graphicx inclusion hook point. |
| S4 | *Done.* Enumerating allocated `\count` registers (kernel allocation pointers, extended registers); confirm `LT@tables` and `\Hy@linkcounter` are covered; cost of writing vectors; initial scratch-register deny list (registers whose segment-entry values differ between a partial and a full run on the corpus). |
| S5 | biblatex `.bcf` contents after an `\includeonly` run; `.bcf` patch feasibility. *Done: patch needed and feasible (decision: patch).* |
| S6 | *Done.* hyperref: `/Dests` name tree, dummy-destination log format, duplicate-destination warning and which definition wins, anchor naming (`section*.N` via `\Hy@linkcounter`), `\HyPL@Entry` semantics. `bookmark`: complete `\BKM@entry` grammar (level, open state, colour and style keys, `srcline`), how the outline is built from it, level-gap handling, and which keys depend on segment state (`id` from `\c@bookmark@seq@number`). |
| S7 | *Done.* Running heads on the first page of a unit (scrbook marks) in a partial run vs a full run; whether A5 suffices; fix if feasible (restoring mark state). Result: heads differ for includes violating A5, and restoring the mark state does not help. Decision: compilation units (§6.1). |
| S8 | *Done.* Inventory of all aux line kinds produced by the thesis corpus; complete §6.7.2. |
| S9 | *Done.* pikepdf merge prototype: two runs → merged PDF with working cross-run links, outline, page labels; verified by §3.3 items 1–3. |
| S10 | *Done.* SyncTeX merge prototype; verified with `synctex view/edit`. |
| S11 | *Deferred to M7 (needs a Windows CI runner).* MiKTeX: format flags, output/aux-directory read order (repeat S2), on-the-fly install settings, `SOURCE_DATE_EPOCH` support, availability of mylatexformat, biber, makeindex and synctex. |

**Done when:** all notes except S11 (deferred to M7) are written and the plan is updated.

### Later milestones

| Milestone | Content | Done when |
|---|---|---|
| **M1** | *Done.* CLI, config, analysis, generated sources, format build, `--full` reference mode, deterministic environment | `--full` matches plain latexmk (§3.3) on the corpus |
| **M2** | *Done.* `fastinc-ini.sty` and `fastinc.sty` (all §6.4 records), run directory preparation, runner (process pool) | records present and parseable; unit tests green |
| **M3** | *Done.* Single-unit incremental path: commit, aux slices (no Python linker, §6.7.1), PDF and SyncTeX merge, logs, `fastinc check` / `build --check` (§3.3 comparison), `--report` | T1, T14, T15, T17 green; `check` passes on the corpus |
| **M4** | Full mode also runs makeindex for a generic `<job>.idx` (the reference and fallback must equal latexmk; found on the pgf manual, whose imakeidx call fails with `-output-directory`), dependency model, compilation units, basic fixpoint with tail runs, biber with `.bcf` patch, makeindex, cold build, lint, fallbacks, `fastinc graph` and dirty reasons in the report | T2–T13, T16, T18, T19, T20 green (T2 via tail run) |
| **M5** | Prediction (§6.9.3) and parallel successor recompilation | T2 and T10 green with parallel runs; benchmark shows a speedup over M4 for T2 |
| **M6** | `watch`, benchmarks, README (usage, assumptions A1–A5, limitations) | §8.4 numbers recorded |
| **M7** | Spike S11 (MiKTeX), MiKTeX adapter, Windows hardening (§6.16), CI matrix | scenario tests green on all four CI targets |

---

## 10. Risks and open questions

| Risk | Mitigation |
|---|---|
| mylatexformat incompatibility with a package | Deny list and config `split_before`; S1 |
| Partial-run differences not captured by the count-register vector (marks, dimens/skips, `\everypar` state, …) | Acceptance tests on every scenario; extend vectors to `\dimen`/`\skip` if needed; S7 |
| Read-order issues with `-output-directory` | Shadow tree (§6.5) excludes stale build files; S2 |
| Text-scan import misses (keys built by macros) | Accepted for v1; `check` detects; config option to mark keys global |
| PDF merge subtleties (OpenAction, forms, OCGs) | Copy rules §6.11.6; fallback on unknown catalog entries |
| Glue cost (bibliography, lists) in every run | Measure in benchmarks; phase 2: checkpoint glue segments without macro effects so they can be skipped |
| Larger merged PDF (duplicated fonts) | Accepted; `--full` for release |

**Phase-2 candidates:**
- TikZ externalize or a per-picture content cache;
- a content-addressed unit cache (CI / cold checkout);
- skippable glue;
- a speculative parallel cold first pass;
- finer units at automatic `\clearpage` points;
- the hyperref `.out` outline route (hyperref without `bookmark`);
- sources outside the main file's directory tree (`\graphicspath{{../x/}}`, `\input{../x}`): a configurable shadow-tree root;
- BibTeX backends.

---

## Appendix A — Reference preamble analysis (user's `scrbook` thesis)

| Lines | Content | Handling |
|---|---|---|
| 1–40 | class (`draft`, `twoside`), setspace, AMS, tensor, inputenc/fontenc/lmodern, babel, csquotes, biblatex+`\addbibresource`, microtype, tables, graphicx, enumitem, siunitx, nomencl, xcolor, pgf, subcaption, gnuplot-lua-tikz, ifdraft, `\usetikzlibrary{external}`, algorithmic, listings, eqparbox | format |
| 28 | `\makenomenclature` | format; `\openout` replayed at runtime by mylatexformat (S1) |
| 41 | `hyperref` | format (S1) |
| 42–43 | orcidlink, todonotes | format |
| 45–189 | siunitx units, nomenclature groups, theorems (per chapter), autoref names, `\subsecref`, math macros, colours, algorithm float via `\DeclareNewTOC` (`loalg`), `\lstset` | format |
| 193–201 | `\ifdraft{\tikzexternalize ...; \todo wrapper}` | split point: line 193, the start of the group containing the deny-list match on line 194 (S1); externalize neutralised (§6.4.3); wrapper works |

**Unit-interface relevant items:**
- `nomencl` (`.nlo` stream with markers);
- biblatex numeric/nty (renumbering → cite imports);
- `longtable` (self aux, `LT@tables` in the vector);
- `eqparbox` (self aux);
- `hyperref` (named destinations, `section*` anchors);
- `bookmark`, auto-loaded by scrbook (`\BKM@entry` outline records in the aux);
- todonotes (`\listoftodos` via `.tdo`);
- `loalg` list;
- `twoside` with `scrbook`'s default `openright` (parity).

## Appendix B — Record formats (written by `fastinc.sty`)

| Record | File | Format |
|---|---|---|
| baseline | main aux | `\fastinc@base{n=v,n=v,...}` (state vector, §6.4.2) |
| entry | main aux | `\fastinc@entry{<seg>}{n=v,...}` (sparse vs baseline) |
| glue exit | main aux | `\fastinc@gexit{<seg>}{n=v,...}` (sparse vs baseline) |
| absolute set | unit aux / main aux | `\fastinc@abs{<seg>}{n,n,...}` |
| unit checkpoint | unit aux | `\fastinc@ckpt{U<k>}{n=v,...}` (complete state vector at unit exit, absolute values) |
| unit name | main aux | `\fastinc@unit{U<k>}{<path>}` (empty for an excluded unit without checkpoint) |
| bookmark levels | main aux | `\fastinc@bkmlevels{<id>=<level>,...}` |
| page map | `<job>.frec` | `P <shipout#> <seg> <\c@page> <\thepage text>` per line |
| file attribution | `<job>.frec` | `F <seg> <path>` per line |
| stream marker | `.nlo` | `%fastinc-seg <seg>` per line |

Segment ids: `G0..Gn` for glue, `U1..Un` for units (k-th `\include` of the body). The driver checks the `\fastinc@unit` records against the include order of the analysis.
