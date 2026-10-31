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
- `glossaries`, `imakeidx`/`makeidx`, `minted`, `cleveref`, `bookmark` package. Detect these and fall back to full builds with a warning (§6.14).

---

## 2. Document assumptions ("discipline")

The user's documents follow these rules. The driver relies on them and checks them where possible.

| # | Assumption | Check / consequence if violated |
|---|---|---|
| A1 | All macro definitions and settings are in the preamble. Unit bodies change only counters, labels, citations, list entries (ToC/LoF/…), nomenclature entries and bookmarks. | Lint (§6.8.4). A unit with a lint hit is marked *global*: its change dirties all successors. |
| A2 | Units are the files given to `\include` in the top-level body of the main file. | Analysis (§6.1). `\include` elsewhere → error. |
| A3 | Body text of the main file between `\include`s ("glue": title page, ToC, lists, `\appendix`, nomenclature, bibliography, …) may change macros (e.g. `\appendix`, `\mainmatter`). | Glue is compiled in **every** run (standard `\includeonly` semantics). Any change to the main-file body dirties everything. |
| A4 | Footnotes are not split across a unit boundary. | Holds for the reference document (`\interfootnotelinepenalty=10000`). Acceptance tests guard it. |
| A5 | Every unit starts with a command that sets running-head marks (`\chapter`, `\addchap`, …), or its first page has no running head. | [S7]; lint warning; acceptance tests guard it. |

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
- **F10** `fastinc check` builds incrementally and with `--full`, then compares the results using §3.3.

### 3.2 Non-functional

- **N1** Incremental build after a typo-sized edit in one unit costs ≈ format load + glue + that unit + merge.
- **N2** Up to `-j N` parallel pdflatex processes (default: CPU count).
- **N3** Requirements: Python ≥ 3.10 and `pikepdf` (qpdf; wheels exist for Linux, macOS and Windows). LaTeX kernel ≥ 2023 (LaTeX hooks, `\ReadonlyShipoutCounter`). Optional for tests: poppler-utils (`pdftoppm`, `pdftotext`), `synctex` CLI.
  - Platforms: Linux, macOS and Windows with TeX Live (tier 1); Windows with MiKTeX (tier 2, §6.16).
- **N4** Deterministic environment for all runs of one build: `SOURCE_DATE_EPOCH` = build start time and `FORCE_SOURCE_DATE=1`, so `\today` and the PDF dates are identical across runs.

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
- **Format files.** `mylatexformat` dumps the TeX state after a partial preamble into a `.fmt` file. Loading it replaces processing that preamble part. Open write streams cannot be dumped. [S1]
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
2. **Split point `s`** (first line not dumped into the format): the first preamble line matching the deny list (§6.3.2), or a config override `format.split_before = "<regex>"`. If `s` falls inside an `\input`ed preamble file, set `s` to the line of that `\input`.
3. **Segments** of the main body: tokenise top-level `\include{...}` occurrences. Units `U1..Un` are in document order; glue segments `G0..Gn` (possibly empty) lie between them. Unit ids are the `\include` arguments (e.g. `chapters/intro`). An argument that is absolute or contains `..` is an error: its aux would be written outside the run directory, which TeX Live refuses (`openout_any = p`).
4. **Fingerprints** (sha256): `pre` (lines `1..s-1` plus inlined files), `post` (lines `s..b-1`), `body` (main-file text from `b` to end, excluding nothing).
5. **Unsupported-package detection** in the preamble → full-build mode (§6.14).

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
- **Path mapping table:** `runs/<r>/main.tex` → user `main.tex`. Used for logs (§6.13) and SyncTeX (§6.12).

### 6.3 Format

#### 6.3.1 Build

```
pdflatex -ini -jobname=pre -output-directory=.fastinc/fmt "&pdflatex" mylatexformat.ltx .fastinc/fmt/pre.tex
```

- Rebuild when `pre`, the TeX Live version string, or the `fastinc-ini.sty` version changes.
- The class options are part of `pre` (the `draft` option freezes `\ifdraft`).
- Run usage: `-fmt=.fastinc/fmt/pre`.

**[S1] verifies:**
- mylatexformat runtime semantics: does it skip the main file up to `\endofdump`? Blank lines plus the marker are designed to work either way.
- That the reference preamble dumps cleanly when split before `hyperref`.
- That SyncTeX works with the format.

#### 6.3.2 Deny list (split before the first match)

| Pattern | Reason |
|---|---|
| `\usepackage{hyperref}` (any options) | Safe default. [S1] may move it into the format. |
| `\tikzexternalize` | Neutralised anyway; keeps the format independent of externalize. |
| `\makeindex`, `\makeglossaries`, `\usepackage{minted}` | Unsupported in v1 → full-build mode. |
| Config additions | User override. |

#### 6.3.3 Deferral (`fastinc-ini.sty`, format mode only)

Commands in the dumped part that open write streams are deferred to runtime:

- `\makenomenclature`: in the format, redefined to set the flag `\fastinc@want@nomencl`. `fastinc.sty` calls the original at runtime.
- The list is extensible (one table in the package).

### 6.4 LaTeX packages

#### 6.4.1 `fastinc-ini.sty` (loaded before `\documentclass` in format builds and in the `--full` reference build)

1. Externalize neutralisation (§6.4.3).
2. Format mode only: the deferral table (§6.3.3), plus storing the original definitions.

#### 6.4.2 `fastinc.sty` (runtime, loaded at the split point)

Requirements:

1. **Segment tracking.** The variable `\fastinc@seg` holds the current segment id:
   - `G0` at `\begin{document}`;
   - `U<k>` at `include/before` [S3: after the initial `\clearpage`];
   - `G<k>` at `include/after`;
   - for an excluded unit: at `include/excluded` [S3].
2. **State records.**
   - The *state vector* is all allocated `\count` registers, determined from the kernel allocation pointers [S4]. It includes the LaTeX counters and, for example, `LT@tables` and `\Hy@linkcounter`.
   - At `\begin{document}` (end of the `AtBeginDocument` hooks), write a baseline `\fastinc@base{...}` to the main aux (`\immediate\write\@mainaux`), as a sparse vector `n=v,...`.
   - At each segment start, write `\fastinc@entry{<seg>}{<sparse vector vs base>}` to the main aux. This happens in every run, for selected and excluded units alike. For excluded units it is written **before** their checkpoints are restored.
   - At each unit end, **after** the final `\clearpage` of `\include` (`include/after`, while the unit aux is still open [S3]), write `\fastinc@ckpt{<unit>}{<registers changed since unit entry: n=v,...>}` to the unit aux. Not at `include/end`: that hook runs before the final `\clearpage`, so the page counter and other changes made by the last shipouts would be missing.
   - At each glue end, write `\fastinc@gexit{<seg>}{...}` to the main aux.
   - Absolute assignments: for each segment, record the set of registers assigned absolutely (hooks on `\setcounter`, counter resets via `\@stpelt`, `\pagenumbering`) as `\fastinc@abs{<seg>}{n,n,...}`, written to the unit aux for units and to the main aux for glue. Used for prediction only (§6.9.3), so missing cases only cost speed.
3. **Restore.** Reading `\fastinc@ckpt` from the aux stores the vector (`\fastinc@ckpt@<unit>`). At `include/excluded`, after LaTeX's own checkpoint restore, the stored registers are assigned globally.
4. **Page map.** At `shipout/before`, `\immediate\write` to `\jobname.fpg`: `<\ReadonlyShipoutCounter> <seg> <\the\c@page> <\thepage expanded via \protected@edef>`.
5. **Segment markers in shared streams.** The streams are `.out` (hyperref outline, `\@outlinefile`) and `.nlo` (`\@nomenclaturefile`). At every segment change, write the line `%fastinc-seg <seg>` into each open stream, using the same write mode (immediate or delayed) as that stream's writer [S6 for `.out`, [S2b] for `.nlo`]. This lets the driver attribute entries to segments.
6. **File attribution.** On `file/before`, `\immediate\write` to `\jobname.ffl`: `<seg> <filename>`. Graphics: hook the graphicx file inclusion (`\Gin@setfile` or the pdftex driver's include macro [S3]) and write the same record.
7. **Aux handlers.** Define `\fastinc@base`, `\fastinc@entry`, `\fastinc@gexit`, `\fastinc@abs` as no-ops, and `\fastinc@ckpt` as store (aux is read at begin and end document).
8. **Externalize neutralisation** (§6.4.3), repeated idempotently.
9. **Deferred commands:** if `\fastinc@want@nomencl` is set, call the original `\makenomenclature`.

#### 6.4.3 Externalize neutralisation

Install a file hook for `tikzlibraryexternal.code.tex/after` [S3]. After the library loads, redefine:

- `\tikzexternalize` → swallow an optional argument, then do nothing;
- `\tikzexternalenable` and `\tikzexternaldisable` → `\relax`.

The user's `\todo` wrapper keeps working.

### 6.5 Runs

**Command:**

```
pdflatex -fmt=<fmt> -interaction=nonstopmode -halt-on-error -file-line-error \
         -synctex=1 -recorder -output-directory=.fastinc/runs/<r> -jobname=main \
         .fastinc/runs/<r>/main.tex
```

- The working directory is the source directory, so relative `\include`, `\input` and `\graphicspath` resolve as usual.
- Environment: N4, `max_print_line=10000`, and `TEXMF_OUTPUT_DIRECTORY` if needed [S2].

**Run directory preparation:**

1. Copy the canonical `main.aux` and all unit aux files, preserving subdirectories.
2. Copy the derived files `.toc .lof .lot .loalg .tdo .bbl .nls`.
3. Create the subdirectories for `\include` paths.

**[S2] verifies** the read search order: that the output directory is read before the source directory, and what happens with stale `main.aux` / unit aux files in the source directory left over from manual builds. If stale files can shadow, the driver must refuse to run while they exist, or the runs must use a copy of the source tree.

**Outputs per run:** `main.pdf`, `main.synctex.gz`, `main.log`, `main.fls`, `main.aux`, unit aux files, `main.fpg`, `main.ffl`, `main.out`, `main.nlo`, `main.bcf`.

A run with selection *S* compiles the glue plus the units in *S*. A **full run** has *S* = all units. A **glue-only run** has *S* = ∅.

### 6.6 Canonical state and commit

`.fastinc/canon/` holds:

- the committed aux of each unit;
- the canonical `main.aux` and derived files;
- `main.bcf` and `main.bbl`;
- `main.nlo` and `main.nls`;
- bookmark records;
- `state.json`.

Per segment, `state.json` stores:
- the source fingerprint (hashes of attributed files),
- the observed entry vector and the exit checkpoint,
- the absolute-assignment set,
- the imported-key values at compile time,
- the artifact pointer `{run dir, PDF page indices, sheet numbers}`,
- the last compile time.

**Commit after a run with selection *S*:**

1. Each unit in *S*: take its aux, its pages (page map), and its per-segment `.out` and `.nlo` entries (by markers).
2. Glue: commit the glue artifacts from the run that §6.9 designates.
3. Store the observed entry vectors of **all** segments from this run, tagged with the run's input snapshot id.
4. Unreferenced run directories are garbage-collected after a successful merge (`--keep-runs` disables this).

### 6.7 Aux linker and aux classification

#### 6.7.1 Derived list files

Reproduce what LaTeX does at `\end{document}`:

1. Read `main.aux`, expanding `\@input{u.aux}` in place.
2. Collect `\@writefile{<ext>}{<text>}`.
3. Write `<text>` lines to `main.<ext>`.

Must equal the full run's files byte for byte; this is a unit test against reference builds.

#### 6.7.2 Line classification

| Aux line | Class |
|---|---|
| `\newlabel{k}{...}` | export `k` (value = whole argument) |
| `\@writefile{ext}{...}` | list contribution |
| `\@setckpt{u}{...}`, `\fastinc@ckpt{u}{...}` | exit state |
| `\fastinc@entry`, `\fastinc@gexit`, `\fastinc@abs`, `\fastinc@base` | state records |
| `\abx@aux@cite{n}{key}` | citation (set and order) |
| `\abx@aux@refcontext`, `\abx@aux@segm`, `\abx@aux@page`, `\abx@aux@number`, other `\abx@aux@*` | biblatex data, key-scoped where a key is present; others global |
| `\gdef\LT@<roman>{...}` (longtable) | *self*: read only by the same unit |
| eqparbox records (exact form [S8]) | *self* (tags are chapter-scoped in the reference document) |
| `\babel@aux{...}` | ignored (language state; A1 lint covers `\selectlanguage`) |
| `\gdef\@abspage@last{N}` | ignored; rewritten to the merged page count in canonical `main.aux` |
| hyperref/nameref internals (`\HyPL@Entry`, `\providecommand...`, `\hyper@...`) [S6] | ignored or main-only |
| `\relax`, `\@input`, header lines | structural |
| anything else | **global**: a change dirties all units and glue; print a warning naming the macro, so the table can be extended |

[S8] produces the actual inventory of aux lines from the test corpus. The table is then completed.

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

Scan unit sources (comments stripped) for top-level occurrences of:

```
\def \gdef \edef \xdef \let \global \newcommand \renewcommand \providecommand
\DeclareRobustCommand \NewDocumentCommand \RenewDocumentCommand \setlength
\addtolength \pagenumbering \pagestyle \appendix \frontmatter \mainmatter
\backmatter \selectlanguage \captionsetup \sisetup \lstset \hypersetup \makeatletter
```

Content inside environments that limit scope (e.g. `{...}` groups, figure environments) is not exempted in v1 (conservative).

- A hit gives a warning with `file:line`, and the unit is marked *global*: whenever it is recompiled, all successors are dirty.
- Config `lint.allow = [...]` lists exceptions.

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
- Run with cwd = source directory: `biber --output-directory <build>/canon main`. Biber then reads `main.bcf` from `canon/` (the output directory is searched first) and resolves `.bib` paths relative to the source directory. Do not pass `--input-directory`: biber would then look for `main.bcf` only there (missing or stale in the source directory).
- Trigger: the citation set or order changed, the `.bib` hash changed, or the `.bcf` structure changed.
- [S5]: does a partial run's `.bcf` contain only the selected units' citations? If yes, the driver patches the citekey list of the canonical `.bcf` (XML: `bcf:citekey` elements in `bcf:section number="0"`) with the union of all units' `\abx@aux@cite` entries, in document order (main aux and unit aux in reading order). Biber never runs on an unpatched partial `.bcf`.
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
   - Keep a name only if its target page belongs to the pages taken from that run, and the name is not a dummy (dummies come from the run log warnings, [S6]).
   - Remap the target page through the map.
   - A duplicate name with different targets → error → fallback (§6.14).
   - Every name referenced by a link or the outline must resolve; a missing name → error → fallback.
   - Write the merged name tree.
3. **Annotations:**
   - Links using named destinations (`/A <</S/GoTo/D (name)>>` or `/Dest (name)`) stay as they are.
   - Direct page-object destinations are remapped via the `(segment, offset)` map.
   - `/P` entries are set to the merged page.
4. **Outline:** built from the bookmark records of all segments in order. Parse hyperref `.out` lines `\BOOKMARK [level][open]{dest}{title}{parent}% n`; the title is a PDF string with TeX octal escapes → bytes. The original `.out` grammar is verified in [S6].
   - Each outline item gets `/Dest (dest)` (named) with `/Parent`, `/First`, `/Last`, `/Next`, `/Prev` and `/Count` (open state as hyperref does it).
   - The catalog `/PageMode` comes from the reference run.
5. **Page labels:** from the page map's `(value, \thepage text)` per page, infer the style: arabic → `/D`, roman → `/r`, Roman → `/R`, alph → `/a`, Alph → `/A`, otherwise a prefix-only label `/P`. Compress into a `/PageLabels` number tree. Compare against the reference in tests.
6. **Catalog and Info:** copy `/Info`, `/OpenAction` (remapped), `/PageMode`, `/PageLayout` and `/ViewerPreferences` from the run that produced `G0`. Do not copy `/Pages`, `/Names`, `/Outlines` or `/PageLabels` (built above).
7. **Output:** write to a temporary file and rename atomically to `main.pdf`.

Expected side effect: a larger file, because font subsets are duplicated per run. This is acceptable; `--full` produces the compact version.

### 6.12 SyncTeX merge

1. Parse each source `main.synctex.gz` according to the grammar [S10].
2. Build a global input table keyed by real path. Map `runs/<r>/main.tex` to the user's `main.tex`; line numbers are unchanged (§6.2). Remap the input tags in all records.
3. Take only the sheets of the selected pages (page map) and renumber them to merged page numbers.
4. Recompute every size and offset field, write the header (`Output:pdf`, `Magnification`, `Unit`, `X Offset`, `Y Offset` copied from the runs; they must be equal, otherwise error) and the postamble, then gzip.
5. Verify with the `synctex` CLI in tests.

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

- unsupported packages (§1 non-goals);
- format build failure;
- a merge error (duplicate or missing destinations, inconsistent SyncTeX header);
- the fixpoint not reached (§6.9.2);
- missing records (e.g. a page without a page-map entry);
- `--full`.

Each trigger prints a one-line reason.

### 6.15 CLI and configuration

```
fastinc build [MAIN] [-j N] [--full] [--build-dir DIR] [--out-dir DIR] [--keep-runs] [-v]
fastinc watch [MAIN] [same options]        # rebuild on change of any recorded input
fastinc check [MAIN] [--samples N]         # incremental vs --full, criterion §3.3
fastinc clean [MAIN]
```

`fastinc.toml` (optional):

```toml
main = "thesis.tex"
jobs = 0                       # 0 = CPU count
build_dir = ".fastinc"
[format]
split_before = []              # extra regexes
[lint]
allow = []                     # e.g. ["\\setlength"]
[aux]
self = []                      # extra regexes of aux lines classified "self"
ignore = []
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

```
pyproject.toml                 # console script: fastinc
src/fastinc/
  cli.py
  config.py
  analysis.py                  # §6.1, §6.2
  fmt.py                       # §6.3
  runner.py                    # §6.5 (process pool)
  texdist.py                   # §6.16 TeX Live / MiKTeX adapter
  state.py                     # §6.6
  aux.py                       # §6.7 parser, classifier, linker
  deps.py                      # §6.8
  scheduler.py                 # §6.9
  tools.py                     # biber, bcf patch, makeindex
  merge_pdf.py                 # §6.11
  merge_synctex.py             # §6.12
  logs.py                      # §6.13
  check.py                     # §3.3 comparison
  tex/fastinc-ini.sty
  tex/fastinc.sty
tests/
  corpus/thesis/               # §8.1 (user preamble + generated content)
  corpus/minimal/              # small documents per feature
  unit/                        # parsers, linker, composition, merges
  scenarios/                   # §8.2
  bench/                       # §8.4
docs/spikes/S1.md ... S10.md
```

---

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

**`tests/corpus/minimal/`** — tiny documents isolating each mechanism, used in spikes and unit tests.

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
| T15 | `\section*` in several units | no duplicate destination names |
| T16 | cold build | §3.3; report wall time vs `--full` |
| T17 | SyncTeX round trip for every segment | §3.3 item 4 |
| T18 | `\setlength` in ch2 body | lint warning; ch2 is global; successors recompiled after ch2 changes |
| T19 | stale `main.aux` in the source directory | behaviour per [S2] |

### 8.3 Unit tests

- Aux parser and classifier.
- Linker output equals the full-run `.toc`/`.lof`/`.lot`/`.loalg`/`.tdo`.
- `.out` parser and outline builder.
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
| S1 | mylatexformat with the thesis preamble split before `hyperref`: dump OK? Runtime skip semantics with the marker plus blank lines? SyncTeX OK? Can `hyperref` and `biblatex` go into the format? `\makenomenclature` deferral works? |
| S2 | `-output-directory` read order (aux and derived files) with cwd = source; stale files in the source directory; `\include` subdirectories; `\graphicspath`; `TEXMF_OUTPUT_DIRECTORY`. S2b: write mode of nomencl's `.nlo` writes. |
| S3 | Hook order: `include/before` relative to the initial `\clearpage`; pages from the final `\clearpage` before `include/after`; whether the unit aux is still open (`\@auxout` = `\@partaux`) at `include/after`, else where to write `\fastinc@ckpt`; existence and timing of `include/excluded` relative to the checkpoint restore; file hook for TikZ libraries; graphicx inclusion hook point. |
| S4 | Enumerating allocated `\count` registers (kernel allocation pointers, extended registers); confirm `LT@tables` and `\Hy@linkcounter` are covered; cost of writing vectors. |
| S5 | biblatex `.bcf` contents after an `\includeonly` run; `.bcf` patch feasibility. |
| S6 | hyperref: `/Dests` name tree, dummy-destination log format, anchor naming (`section*.N` via `\Hy@linkcounter`), `.out` grammar and write mode, `\HyPL@Entry` semantics. |
| S7 | Running heads on the first page of a unit (scrbook marks) in a partial run vs a full run; whether A5 suffices; fix if feasible (restoring mark state). |
| S8 | Inventory of all aux line kinds produced by the thesis corpus; complete §6.7.2. |
| S9 | pikepdf merge prototype: two runs → merged PDF with working cross-run links, outline, page labels; verified by §3.3 items 1–3. |
| S10 | SyncTeX merge prototype; verified with `synctex view/edit`. |
| S11 | MiKTeX: format flags, output/aux-directory read order (repeat S2), on-the-fly install settings, `SOURCE_DATE_EPOCH` support, availability of mylatexformat, biber, makeindex and synctex. |

**Done when:** all notes are written and the plan is updated.

### Later milestones

| Milestone | Content | Done when |
|---|---|---|
| **M1** | CLI, config, analysis, generated sources, format build, `--full` reference mode, deterministic environment | `--full` matches plain latexmk (§3.3) on the corpus |
| **M2** | `fastinc-ini.sty` and `fastinc.sty` (all §6.4 records), run directory preparation, runner (process pool) | records present and parseable; unit tests green |
| **M3** | Single-unit incremental path: commit, aux linker, PDF and SyncTeX merge, logs | T1, T14, T15, T17 green |
| **M4** | Dependency model, basic fixpoint with tail runs, biber with `.bcf` patch, makeindex, cold build, lint, fallbacks | T2–T13, T16, T18, T19 green (T2 via tail run) |
| **M5** | Prediction (§6.9.3) and parallel successor recompilation | T2 and T10 green with parallel runs; benchmark shows a speedup over M4 for T2 |
| **M6** | `watch`, `check`, benchmarks, README (usage, assumptions A1–A5, limitations) | §8.4 numbers recorded |
| **M7** | MiKTeX adapter, Windows hardening (§6.16), CI matrix | scenario tests green on all four CI targets |

---

## 10. Risks and open questions

| Risk | Mitigation |
|---|---|
| mylatexformat incompatibility with a package | Deny list and config `split_before`; S1 |
| Partial-run differences not captured by the count-register vector (marks, dimens/skips, `\everypar` state, …) | Acceptance tests on every scenario; extend vectors to `\dimen`/`\skip` if needed; S7 |
| Read-order issues with `-output-directory` | S2; fallback: copy the source tree per run |
| Text-scan import misses (keys built by macros) | Accepted for v1; `check` detects; config option to mark keys global |
| PDF merge subtleties (OpenAction, forms, OCGs) | Copy rules §6.11.6; fallback on unknown catalog entries |
| Glue cost (bibliography, lists) in every run | Measure in benchmarks; phase 2: checkpoint glue segments without macro effects so they can be skipped |
| Larger merged PDF (duplicated fonts) | Accepted; `--full` for release |

**Phase-2 candidates:**
- TikZ externalize or a per-picture content cache;
- a content-addressed unit cache (CI / cold checkout);
- skippable glue;
- a speculative parallel cold first pass;
- finer units at automatic `\clearpage` points.

---

## Appendix A — Reference preamble analysis (user's `scrbook` thesis)

| Lines | Content | Handling |
|---|---|---|
| 1–40 | class (`draft`, `twoside`), setspace, AMS, tensor, inputenc/fontenc/lmodern, babel, csquotes, biblatex+`\addbibresource`, microtype, tables, graphicx, enumitem, siunitx, nomencl, xcolor, pgf, subcaption, gnuplot-lua-tikz, ifdraft, `\usetikzlibrary{external}`, algorithmic, listings, eqparbox | format (split before line 41) |
| 28 | `\makenomenclature` | deferred (§6.3.3) |
| 41 | `hyperref` | split point (deny list); [S1] may move it into the format |
| 42–43 | orcidlink, todonotes | after split |
| 45–189 | siunitx units, nomenclature groups, theorems (per chapter), autoref names, `\subsecref`, math macros, colours, algorithm float via `\DeclareNewTOC` (`loalg`), `\lstset` | after split; cheap |
| 193–201 | `\ifdraft{\tikzexternalize ...; \todo wrapper}` | externalize neutralised (§6.4.3); wrapper works |

**Unit-interface relevant items:**
- `nomencl` (`.nlo` stream with markers);
- biblatex numeric/nty (renumbering → cite imports);
- `longtable` (self aux, `LT@tables` in the vector);
- `eqparbox` (self aux);
- `hyperref` (named destinations, outline markers, `section*` anchors);
- todonotes (`\listoftodos` via `.tdo`);
- `loalg` list;
- `twoside` with `scrbook`'s default `openright` (parity).

## Appendix B — Record formats (written by `fastinc.sty`)

| Record | File | Format |
|---|---|---|
| baseline | main aux | `\fastinc@base{n=v,n=v,...}` (allocated `\count` registers, all) |
| entry | main aux | `\fastinc@entry{<seg>}{n=v,...}` (sparse vs baseline) |
| glue exit | main aux | `\fastinc@gexit{<seg>}{n=v,...}` (sparse vs baseline) |
| absolute set | unit aux / main aux | `\fastinc@abs{<seg>}{n,n,...}` |
| unit checkpoint | unit aux | `\fastinc@ckpt{<unit>}{n=v,...}` (registers changed within the unit, absolute values) |
| page map | `main.fpg` | `<shipout#> <seg> <\c@page> <\thepage text>` per line |
| file attribution | `main.ffl` | `<seg> <path>` per line |
| stream marker | `.out`, `.nlo` | `%fastinc-seg <seg>` per line |

Segment ids: `G0..Gn` for glue, `U1..Un` for units. The unit-id ↔ `\include` argument map is written once per run as `\fastinc@unit{U<k>}{<include arg>}` in the main aux.
