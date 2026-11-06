# chapmk design

How chapmk works and why. This document describes the current design; the reasons behind
decisions are in the spike notes (`docs/spikes/S#.md`) and the review (`docs/review/M8.md`),
which are referenced as S# and C#/D#/E#/U#/R#. The module map with every public function is
in `src/chapmk/CLAUDE.md` (and `src/chapmk/tex/CLAUDE.md` for the LaTeX packages); user
documentation is in `README.md` and `docs/configuration.md`.

Section numbers in the code, tests and module maps (`§6.9.3`) refer to this document. It
replaces the former implementation plan (`PLAN.md`, in the git history), whose numbers it
keeps for sections 1–6 and 8, so references in the spike notes and the review still point
to the right topic; Appendix C maps the rest.

Terms: the *build directory* is `.chapmk/<jobname>/` next to the main file (configurable);
paths like `canon/` are relative to it. A *unit* is an `\include`d file, a *segment* is a unit
(`U<k>`) or the main-file text around the includes (*glue*, `G<k>`), a *run* is one pdflatex
process of the incremental builder, a *batch* the runs of one iteration.

---

## 1. Goal

One command, `chapmk build main.tex`, replaces `latexmk -pdf -synctex=1`. It produces the same
document (§3.3) and rebuilds faster after small edits by:

- precompiling the static part of the preamble into a format file;
- recompiling only the `\include` units an edit affects, with `\includeonly`;
- compiling independent units in parallel, with predicted start states;
- merging the runs' PDFs and SyncTeX files into one `main.pdf` and `main.synctex.gz`, with
  working links, outline, page labels and document info.

**Principle: correctness first.** Every shortcut is guarded by a verification or falls back to
a plain full build (§6.14). `chapmk check` compares a build with a plain full build (§3.3).

### Non-goals

- Engines other than pdfLaTeX; TeX distributions other than TeX Live and MiKTeX.
- Units other than `\include` (no automatic splitting at `\chapter`).
- The user's TikZ externalize settings (prefix, shell escape, system calls): chapmk keeps
  `\tikzexternalize` but makes the figures itself (§6.4.3, §6.17).
- Byte-identical PDFs.
- Packages that write their own index or glossary files or need shell escape: `glossaries`,
  `imakeidx`/`makeidx`, `minted`, `cleveref` (full builds with a warning; one table,
  `facts.UNSUPPORTED_PACKAGES`, for the preamble scan and the runtime check).
- biblatex with another backend than biber, classic BibTeX, biblatex refsections.
- hyperref without the `bookmark` package (the outline comes from bookmark's records).

---

## 2. Document assumptions

chapmk relies on these rules and checks them where it can (README "Document assumptions").

| # | Assumption | Check / consequence if violated |
|---|---|---|
| A1 | Macro definitions and settings are in the preamble. Unit bodies change only counters, labels, citations, list entries, nomenclature entries and bookmarks. | Lint (§6.8.4): a unit with a hit is *global* and compiled in every run. |
| A2 | Units are the files given to `\include` in the top-level body of the main file. | Analysis (§6.1). `\begin{document}` not in the main file, or an `\include` inside a group: full builds. |
| A3 | The main-file body between the includes (glue: title page, lists, `\appendix`, bibliography, …) may change macros. | The glue is compiled in every run (`\includeonly` semantics). An edit of the main-file body is a cold build. |
| A4 | No footnote is split across an `\include` boundary. | Acceptance tests. |
| A5 | Every compilation unit starts with a chapter-level heading. | An include that does not start with one joins the preceding compilation unit (§6.1; S7: running heads). |

---

## 3. Requirements

### 3.1 Functional

- **F1** Like `latexmk -pdf -synctex=1`: `main.pdf` and `main.synctex.gz` next to `main.tex`
  (or in `--out-dir`), exit code 0 on success.
- **F2** Incremental builds: after an edit only the affected units are recompiled, to a
  fixpoint (§6.9).
- **F3** Cold builds (no state) are correct and use parallel runs after the first one.
- **F4** SyncTeX forward and inverse search across the merged PDF, including the glue.
- **F5** Internal links, outline, page labels and document info work in the merged PDF.
- **F6** biblatex with biber, nomencl with makeindex.
- **F7** Errors with paths and line numbers of the user's sources; on an error the previous
  `main.pdf` is kept.
- **F8** `chapmk watch` (future).
- **F9** `chapmk build --full`: a plain sequential build (latexmk-equivalent, same
  environment).
- **F10** `chapmk check` (`build --check`): build, build with `--full`, compare (§3.3);
  exit code 1 and a report on a difference.
- **F11** Coexistence with plain LaTeX builds in the same directory: chapmk never reads build
  outputs from the source directory (shadow tree, §6.5) and writes only `main.pdf`,
  `main.synctex.gz` and `main.log` there, each replaced atomically, the PDF and SyncTeX file
  always from the same build.

### 3.2 Non-functional

- **N1** A typo-sized edit in one unit costs about format load + glue + that unit + merge.
- **N2** At most `-j N` parallel pdflatex processes (default: CPU count).
- **N3** Python ≥ 3.11 with `pikepdf`; LaTeX kernel ≥ 2025-11-01 (TeX Live 2025; hooks,
  mark classes); `check` also needs poppler (`pdfinfo`, `pdftoppm`, `pdftotext`) and the
  `synctex` CLI. Platforms: TeX Live on Linux, macOS and Windows; MiKTeX (§6.16).
- **N4** Deterministic environment: `SOURCE_DATE_EPOCH` and `FORCE_SOURCE_DATE=1`. The epoch is
  fixed per canonical state (set at the cold build, from the environment or the start time)
  and used by all later runs, `--full` and the `check` reference: reused pages and new runs
  show the same dates (README: dates are fixed at the first build).

### 3.3 Acceptance criterion ("identical output")

The reference is `chapmk build --full`: plain sequential runs on the unmodified sources with
only `chapmk-ini.sty` injected (externalize redirection, §6.4.3) and the same environment
(N4). The acceptance tests also compare `--full` with latexmk. A build must match the
reference in:

1. page count; every page rendered at 150 dpi (`pdftoppm`), pixel-identical;
2. extracted text per page (`pdftotext -layout`);
3. page labels; outline (titles, levels, open state, target page and position); link
   annotations (rectangle, target page and position, or URI); document info and catalog
   entries (S13);
4. SyncTeX: `synctex view` at sampled lines of every source file returns the same page and
   position, `synctex edit` at those positions the same file and line.

Not required: byte identity (object order, font subset names, `/ID` differ).

---

## 4. Background: LaTeX mechanisms used

- **`\include` / `\includeonly`.** `\include{u}` does `\clearpage`, writes into `u.aux`, ends
  with a counter checkpoint `\@setckpt{u}{…}` and another `\clearpage`. With `\includeonly`,
  excluded units are not typeset; their `u.aux` (read at `\begin{document}`) still provides
  labels, list entries and the checkpoint, restored where the `\include` stands. Main-file
  text is always typeset.
- **Aux files** carry cross-references, list entries (`\@writefile`), biblatex data, package
  data (longtable, eqparbox). At `\end{document}` LaTeX reads all aux files again and writes
  `.toc`, `.lof`, … from the `\@writefile` lines.
- **`bookmark`** writes each outline entry as `\BKM@entry{id=…,dest={<hex>},…}{<hex title>}`
  into the main aux; level and parent live in run-internal macros (S6).
- **Formats.** `mylatexformat` dumps the state after a part of the preamble into a `.fmt`
  file. At runtime it skips the main file up to the line with `\endofdump` (or
  `\begin{document}`) and executes that line. Open write streams are replayed (S1). pdfTeX
  does not dump everything (§6.3.3, S13).
- **Hooks** (kernel ≥ 2020-10): `include/before`, `include/end`, `include/after`,
  `include/excluded` (S3), `file/before`, `file/after`, `shipout/before`
  (`\ReadonlyShipoutCounter`).
- **Named destinations.** hyperref links refer to names in the catalog's `/Dests` name tree.
  A referenced but undefined name gets a dummy destination and a log warning (S6).
- **SyncTeX files** (gzip text): `Input:<tag>:<path>` lines, one block per sheet with records
  referring to tags and lines, a postamble with byte offsets (S10).

---

## 5. Architecture

```
 analysis ─► shadow tree ─► format ─► fixpoint loop ──────────────────────► merge ─► publish
                                       │  dirty rules (dirty.py)              PDF (pikepdf)
                                       │  schedule: groups, prediction        SyncTeX
                                       │  runs in parallel (runner.py)        log
                                       │  commit to canon/ (canon.py)
                                       │  biber, makeindex (tools.py)
                                       └─ repeat until nothing is dirty
         fallback for anything unsupported or inconsistent: full mode (fullbuild.py)
 LaTeX side: chapmk-ini.sty (format and full builds), chapmk.sty (incremental runs)
```

One build (`incremental.build`):

1. Analyse the main file (§6.1); sync the shadow tree (§6.5).
2. Decide the mode: full mode for a fallback reason (§6.14); otherwise cold (no usable
   canonical state, §6.6) or incremental.
3. Build or reuse the format (§6.3).
4. Fixpoint loop (§6.9): compute the dirty units; run them in a batch of up to `-j` runs,
   each with the glue; commit the runs in document order; run biber and makeindex; repeat.
5. Merge the committed pages into the published PDF, SyncTeX file and log (§6.11–6.13); a
   build that changed nothing keeps the published files.

The Python driver holds all logic; the LaTeX packages only install hooks and write records
(Appendix B). Module layering and APIs: `src/chapmk/CLAUDE.md`.

---

## 6. Detailed design

### 6.1 Project analysis

Input: the main file (argument or `main` in `chapmk.toml`). Done without TeX (`analysis.py`,
`texsource.py`), respecting comments, verbatim environments and conditionals.

1. **Preamble:** lines `1 .. b-1`, `b` the line with `\begin{document}`. Files `\input` in
   the preamble are inlined for the split detection.
2. **Split point `s`:** the first preamble line that matches the deny list (§6.3.2) or a
   `format.split_before` pattern. A match inside a command or group spanning several lines
   (`\ifdraft{…}`) moves `s` to the start of that command; a match inside an `\input` file
   moves it to the `\input` line (S1).
3. **Includes:** top-level `\include{…}` in the body, in order (`U1..Un`); the glue
   `G0..Gn` lies between them. Arguments that are absolute, contain `..` or spaces are
   errors (the unit aux would leave the run directory).
4. **Fingerprints** (sha256): `pre` (lines `1..s-1` and inlined files), `post` (lines
   `s..b-1`), `body` (from `b` to the end).
5. **Compilation units** (A5, S7): an include whose first command is a chapter-level heading
   (`\chapter`, `\addchap`, `\part`, `\addpart`, starred forms, config `units.heading`)
   starts a unit; any other include joins the preceding one. Without any such include
   (article-like classes) `\section`/`\addsec` count. The scheduler selects whole
   compilation units; segment ids and records stay per include.
6. **Fallback reasons:** unsupported packages in the preamble, refsections, `\documentclass`
   not before the split line, … (§6.14).

### 6.2 Generated sources

Generated files keep the user's line numbers, so errors and SyncTeX need only a path mapping.

- **Format source `fmt/pre.tex`:** line 1 is prefixed with
  `\def\chapmk@formatbuild{}\RequirePackage{chapmk-ini}`; lines `1..s-1` verbatim; then the
  probes for state a format loses and the capture of the main vertical list (§6.3.3), and
  `\endofdump`.
- **Run main `runs/<r>/chapmk-run.tex`:** lines `1..s-1` are empty except line `s-1`, which
  holds `\csname endofdump\endcsname`, the driver parameters (`\chapmk@denynames`,
  `\chapmk@listexts`), `\usepackage{chapmk}` and `\includeonly{<selection>}`
  (`\includeonly{}`: glue only; none: all units). The rest is the main file verbatim. The
  file has a fixed name and is found via `TEXINPUTS`: TeX reads the command line with the
  format's catcodes, where a path with `_` breaks under the `underscore` package. (MiKTeX:
  relative path, §6.16.)
- **Full mode input:** the main file with `chapmk-ini.sty` loaded first.
- **Path mapping:** the run main → the user's main file; the shadow tree → the source
  directory (logs §6.13, SyncTeX §6.12).

### 6.3 Format

#### 6.3.1 Build and reuse

`pdflatex -ini -jobname=pre "&pdflatex" mylatexformat.ltx fmt/pre.tex` with the shadow tree as
working directory (`texdist.format_build`). Runs load it by name via `TEXFORMATS` and
`-fmt=pre` (an absolute `-fmt` path breaks `-recorder`, S1); MiKTeX by `--undump=<path>`.

The format is reused while its stamp is unchanged: `pre`, the split line, the distribution
version string, `chapmk-ini.sty`, `chapmk.sty`, the chapmk version, the digests of the source
files the format build read and the stat signatures (size, mtime) of the distribution files it
read (from `pre.fls`; a `tlmgr` update does not change the version string). The class
options are part of `pre` (`draft` freezes `\ifdraft`).

#### 6.3.2 Deny list (split before the first match)

| Pattern | Reason |
|---|---|
| `\tikzexternalize` | Redirected at runtime (§6.4.3); keeps the format independent of it. |
| Code that creates PDF images or form xobjects (`analysis.DENY_SPLIT`) | Not dumped by pdfTeX (§6.3.3). |
| `\makeindex`, `\makeglossaries`, `minted` | Unsupported (full mode). |
| `format.split_before` | User patterns. |

#### 6.3.3 State a format does not keep (S13)

- `\openout` calls (e.g. `\makenomenclature`) are replayed by mylatexformat (S1).
- `\pdfcatalog`, `\pdfinfo`, `\pdfnames`, `\pdftrailer` entries are not dumped. In format builds
  `chapmk-ini.sty` wraps them (and their expl3 names) and records each call in the deferral
  table `\chapmk@deferred`; `chapmk.sty` replays the table at the split point of every run and
  restores the primitives.
- Nodes left on the main vertical list by the format part (e.g. xcolor's unmatched
  `\pdfcolorstack 0 push`) are not dumped; without them a colour left open across a page
  break would end on its page. The format source moves them into a dumped box with a local
  output routine; `chapmk.sty` puts them back at the split point.
- Detected and rejected (format build fails → full mode with the reason): immediate PDF
  objects (pdfTeX's `dangling objects discarded`, e.g. `cmap`), colour stacks
  (`\pdfcolorstackinit`), catalog calls without a braced argument, form xobjects and images.
  Moving the split before `cmap` does not help: the fonts it affects are loaded earlier.

### 6.4 LaTeX packages

Both packages contain hooks and records only, prefix `\chapmk@`, version equal to
`chapmk.__version__`. Details: `src/chapmk/tex/CLAUDE.md`; record formats: Appendix B.

#### 6.4.1 `chapmk-ini.sty`

Loaded before `\documentclass` in format builds and full builds: records the kernel register
boundary (`\count10`, S4), the externalize redirection (§6.4.3), the deferral table and the
main-vertical-list capture (§6.3.3, format builds only).

#### 6.4.2 `chapmk.sty`

Loaded at the split point of incremental runs.

1. **Segment tracking.** `\chapmk@seg` is `G0` from `\begin{document}`, `U<k>` at
   `include/before` (after the first `\clearpage`, unit aux open), `G<k>` at `include/after`
   (after the last `\clearpage`, S3). Excluded units switch in a `\@setckpt` wrapper and at
   `include/excluded`.
2. **State vector** (S4): the counters of the kernel checkpoint list, plus every `\count`
   register allocated after the kernel, minus run-local registers (`Hy@abspage`, `BKM@id`,
   `calc@Acount`, `calc@Bcount`, config `state.ignore`), plus one pseudo register per kernel
   mark class (`100000 + <marks register>`: a digest of the last mark's text). The number→name
   map for messages comes from the allocation lines in the logs.
   - Baseline at `\begin{document}`; per segment an entry vector (sparse against the
     baseline) in the main aux, written before an excluded unit's checkpoint is restored;
     per glue segment its exit; per unit its complete exit vector in the unit aux, after the
     final `\clearpage` (complete, because the restore itself can change scratch registers).
   - Absolute assignments per segment (`\setcounter`, `\@stpelt`, `\pagenumbering`, marks)
     for the prediction (§6.9.3).
   - Mark texts of the `page` and `column` regions at a unit's end, restored for an excluded
     unit. Primitive marks cannot be restored: their use is a persistent fallback.
3. **Restore.** An excluded unit's checkpoint assigns, after the kernel restore, all stored
   post-kernel registers (not run-local). Without it partial runs lose state such as
   `Hy@linkcounter`, biblatex citation order, `LT@tables` (S4).
4. **Records file `\jobname.frec`** (one write stream for all): page map (`P`), file
   attribution (`F`, from `file/before` and the graphics inclusion), elapsed TeX time (`T`),
   eqparbox tag uses (`Q`), list files (`L`), per-unit layout (`O`), mark classes (`K`).
5. **Markers in shared files:** `%chapmk-seg <seg>` lines in the `.nlo` stream; list-file
   markers `\chapmk@lmark{U<k>}` / `{/<seg>}` (no-ops) written while the aux files are read at
   `\end{document}`, which delimit each unit's list entries (§6.7.1).
6. **Aux handlers:** the chapmk aux statements are no-ops except the checkpoint store.
   chapmk.sty allocates no registers (they would enter the vector).
7. **Header records:** counter registers and reset lists, layout flags (twoside,
   openright), bookmark levels at the end.
8. Replays the deferral table and the captured nodes (§6.3.3).

#### 6.4.3 Externalize redirection

A hook after `tikzlibraryexternal.code.tex` replaces externalize's system call by chapmk's
picture handler (S12): the user's `\tikzexternalize[…]` options apply, every picture not
disabled by `\tikzexternaldisable` is externalized, `\tikzsetnextfilename` works, but figures
are made and read by chapmk in its own cache (§6.17), without shell escape and without the
user's figure directory. Documents without `\tikzexternalize` are not affected.

### 6.5 Runs

```
pdflatex -fmt=pre -interaction=nonstopmode -halt-on-error -file-line-error -synctex=1 \
         -recorder -output-directory=<build>/runs/<r> -jobname=<job> chapmk-run.tex
```

(All engine flags come from `texdist.py`.)

**Shadow tree** `src/`: the working directory of every TeX run, a mirror of the source tree
made of symlinks to the user's files, without the build directory, `.git`, the main job's
build outputs (`<job>.aux`, `.toc`, any `<job>.lo*`, …) and the unit aux files. Relative
`\input`, `\include`, `\graphicspath` resolve as usual, and stale files of manual builds
cannot be read: TeX reads the output directory first and the working directory second (S2;
MiKTeX reads the working directory first, S11, which the shadow tree also covers). Synced once
per build, shared read-only by parallel runs. Where symlinks are unavailable (Windows without
the privilege): hardlinks, else copies. Limitation: paths leaving the source tree
(`\input{../x}`) do not resolve.

**Run directory** `runs/<r>/`: the canonical main and unit aux files, the derived files (list
files, `.bbl`, `.nls`), the include subdirectories and the run main. Excluded units of a
parallel run get predicted checkpoints (§6.9.3). Outputs: `.pdf`, `.synctex.gz`, `.log`,
`.fls`, aux files, `.frec`, `.nlo`, `.bcf`, list files.

A run compiles the glue plus its selection: all units (full run), some, or none (glue-only
run). Runs execute in a thread pool that waits on subprocesses (no fork); each process runs
in its own process group (§6.15).

**First-page material** (S15): what is on the main vertical list before the first page
(`\begin{document}` material such as hyperref's `Doc-Start` destination, the S13 nodes) and
LaTeX's `shipout/firstpage` hook belong to the first page TeX ships. In a full build that is
the document's first page. When the document starts with an `\include` that a run excludes,
it would be a later page of the run. Before the first excluded unit's checkpoint, if the run
has shipped nothing yet, `chapmk.sty` ships them on an extra page (`\RawShipout`: no page
record, so the merges skip it); their effects (e.g. the colour stack) still hold for the
run's pages.

### 6.6 Canonical state and commit

`canon/` holds the committed state: unit aux files, the canonical main aux, the list files,
`.bcf`/`.bbl`, `.nlo`/`.nls`, and `state.json`, which stores (`state.py`):

- the epoch, fingerprints, format stamp and include list of the state;
- per segment: the run that committed it and its page indices; its attributed source files
  with digests; its vectors (entry, exit, absolute set); citations (`.bcf` elements); eqparbox
  tags; picture keys; per unit the inputs it was compiled with (entry, imported values, list
  files read, self-data stability) and its odd-page flag;
- global inputs (source files read by no segment, by the format build, `.bib` files) with
  digests, distribution files with stat signatures, the document's list suffixes, the glue
  input hashes, and pending dirty reasons if a build stopped before the fixpoint.

**Commit of a run** (`canon.commit_run`, in document order within a batch): the aux files of
its compiled units; for its compiled units and all glue segments the pages, vectors,
citations, nomenclature entries and aggregates. The canonical main aux is the run's main aux
with the unit content of the units it did not compile kept from the previous canonical main
aux (§6.7.2). Then the list files (§6.7.1) and the tools (§6.10).

**Cold build triggers:** no or unreadable state, the commit journal found (below), a changed
format stamp (incl. the chapmk version), main-file fingerprints, include list, global inputs
or distribution files, or another `STATE_VERSION`. A cold build is the fixpoint loop from an
empty `canon/` with all units dirty (§6.9.4).

**Robustness** (C7): every file kept between builds is written atomically (temporary file,
rename). While a batch commits, `canon/.in-progress` exists (`canon.committing`); a build that
finds it starts cold. Full mode keeps `full/.in-progress` while passes run; a build that finds
it empties `full/`.

### 6.7 Aux files

#### 6.7.1 List files

List files (`.toc`, `.lof`, …) are written by TeX, not by chapmk: TeX expands their content
while writing, and aux macros like `\babel@aux` add entries, so a Python linker is not exact.
Every run reads all aux files at `\end{document}` and writes complete list files.

In a parallel batch no run reads all new contributions. The canonical list files are the last
run's, with each unit's section (between its list-file markers) taken from the run that
committed the unit; the bytes are TeX's, so the result is exact. Without markers, a glue-only
run rewrites them. A document's list files are found at runtime (`L` records), so lists of
other packages (`.loa`, `\DeclareNewTOC`) are handled like `.toc`.

Known cost: a deferred glue write (e.g. `\appendix` writes to `.toc`) is flushed at the next
shipout, i.e. inside the following unit's entries in a full run and inside a later unit's when
that unit is excluded; this can cost one glue-only run.

#### 6.7.2 Statement classes

Aux files are parsed as brace-balanced statements (S8). Classes (`auxfile.classify`):

| Statement | Class |
|---|---|
| `\newlabel{k}{…}` | label: export of key `k` (value = the whole argument) |
| `\@writefile{ext}{…}` | list contribution |
| `\@setckpt`, `\chapmk@ckpt`, other `\chapmk@…` records | state records; `\chapmk@entry` delimits the main-aux slices of the segments |
| `\abx@aux@cite`, `\abx@aux@segm` | citation (set and order; one line per key and citation command, S5) |
| `\abx@aux@backref`, other `\abx@aux@*` in a unit slice | unit content |
| keyed `\abx@aux@*` outside unit slices (`refcontext`, `number`, …) | biblatex data, merged per key without the run-local instcount; part of the citation value |
| `\gdef\LT@…` (longtable), `\pgfsyspdfmark` | *self* |
| eqparbox `\eqp@…@<tag>` | *self* per tag, owners from `Q` records (§6.9.1) |
| KOMA `@altsecnumformattrue` | aggregate (OR over the typeset segments) |
| `\BKM@entry`, `\chapmk@bkmlevels` | outline, merge only |
| `\babel@aux`, `\relax`, `\@input`, `\providecommand`, … | structural |
| `\gdef\@abspage@last{N}` | rewritten to the merged page count |
| anything else | *global*: a change dirties all units, with a warning naming the macro |

**Canonical main aux** (S8): the committing run's main aux, where each excluded unit's slice
gets back the unit content (outline entries, citations, backrefs, biblatex data, pdf marks)
of its committed slice, and the aggregates are merged. A run's input main aux omits the
citations of its excluded units (biblatex would treat them as removed and drop e.g. the
`defernumbers` data).

### 6.8 Dependency model

#### 6.8.1 Inputs of a unit

1. The format and preamble (`pre`, `post`) and the main body: a change is a cold build.
2. Its own sources: files attributed by `F` records, with digests. Source files read by no
   segment are global inputs; distribution files are tracked by size and mtime (§6.6).
3. Its entry state (§6.9.1).
4. Imports: label and citation keys it references, found by a text scan of its attributed
   files (`deps.TokenScan`: a key delimited by braces, brackets, commas or whitespace, not as
   a `\label` argument; comments count, a safe over-approximation). A label's value is its
   whole `\newlabel` argument; a citation's value is its `.bbl` block, position and keyed
   biblatex aux data.
5. Self data: its *self* statements must be the same before and after the compile.
6. The list files it typesets (`\tableofcontents` → `.toc`, `\printbibliography` → `.bbl`,
   …; an unknown list command counts all list files) or reads (`F` records).

#### 6.8.2 Inputs of the glue

The glue is compiled in every run; its pages are valid only if they were produced under the
final canonical state. Its inputs: the list and tool files, the values of keys referenced by
the main file and glue files, the glue aux data (list typesetting data, eqparbox, aggregates,
backrefs, unclassified statements, glue self data), and its sources.

#### 6.8.3 What propagates

Exit state → successors' entries; exports → importers; list contributions → list files →
readers; citations → `.bcf` → biber → `.bbl` → importers; nomenclature entries → `.nlo` →
makeindex → `.nls` → readers; outline records → merge only.

#### 6.8.4 Lint (A1)

The unit sources (comments and verbatim stripped) are scanned for commands with effects
beyond the unit (`lint.py`):

- **local-effect commands** (`\def`, `\newcommand`, `\setlength`, `\captionsetup`, `\lstset`,
  `\definecolor`, `\makeatletter`, `\catcode`, …) are a hit only outside an explicit group: an
  environment, `\begingroup…\endgroup`, or a brace group that is not a macro argument (a `{`
  directly after a control word, `}` or `]` counts as an argument);
- **global-effect commands** (`\gdef`, `\global`, `\newcounter`, `\pagenumbering`,
  `\appendix`, `\selectlanguage`, `\hypersetup`, `\usetikzlibrary`, …) are always a hit.

A hit is a warning with `file:line`; the unit becomes *global*: its state is not in the
checkpoints, so it is compiled in every run, and when it is dirty itself all later units are
compiled in the same run. Config: `lint.allow`, `lint.verbatim`, `lint.shortverb`. Results are
cached by file content (`canon/lint-cache.json`).

**Slow glue (hint):** a glue block taking ≥ 0.5 s in every run (`T` records) is reported with
its line range and whether it could move into an `\include` (a hint, not a warning: it depends
on the machine).

### 6.9 Fixpoint loop

#### 6.9.1 Dirty rules

At the start of a build (`dirty.DirtyRules.initial`): units never compiled, with changed
sources, or with pending reasons; the glue if its sources changed or it was pending.

After each batch (`after_run`), a unit is dirty if:

- (a) its sources changed;
- (b) an imported value changed;
- (c) it was compiled and its self data changed (rerun until stable);
- (d) it was not compiled and its observed entry vector differs from the one it was compiled
  with, ignoring the counters its leading numbered heading resets (`\cl@` closure). Without
  prediction, all later units join it (tail rule);
- (e) it uses an eqparbox tag whose width changed; aggregate or unclassified aux data changed
  (all units);
- (f) a list file it reads changed;
- (g) it was never compiled, or pictures were exported in it (§6.17).

The glue is invalid if its input hashes (§6.8.2) differ from those its committed pages were
produced with, or its sources changed. The loop ends when no unit is dirty and the glue is
valid: every committed segment was then compiled from the final canonical state. After 8
iterations without fixpoint: full mode.

A changed eqparbox tag used by segments last compiled in different runs is a fallback (C13): a
partial run computes the width from its own boxes only.

#### 6.9.2 Batches

Per iteration (`schedule.Schedule`):

1. **Selection:** the compilation units of the dirty units; a global unit is in every run,
   and when it is dirty all later units join (§6.8.4). All units: a full run; none: a
   glue-only run.
2. **Groups:** contiguous groups of the selected units, balanced by page count, at most `-j`.
   One run (a *tail run*) if `-j 1`, a global unit exists, a segment of the zone has no
   vectors yet, or a unit was mispredicted twice in a row.
3. **Runs** in parallel, each with the glue; committed in document order; the glue pages come
   from the last run; biber and makeindex once per batch.

A typo is one run: the unit's exit, exports and contributions are unchanged and the glue stays
valid.

#### 6.9.3 Prediction

With several groups, later groups start from states that earlier groups have not produced
yet. They are predicted (`predict.py`):

1. **Composition model:** a segment with old entry *E*, old exit *X*, absolute set *A* and new
   entry *E'* exits with `X'[r] = X[r]` for `r ∈ A`, else `X[r] + E'[r] − E[r]`. Registers a
   segment does not modify (no absolute assignment, exit = entry) pass through. **Odd start
   pages:** with twoside and openright (per unit, `O` records, so a local `open=any` counts) a
   unit starting with a chapter-level heading starts on the next odd page: its page counter
   composes as `X + odd(E') − odd(E)`.
2. **Predict** from the first unit of the batch (its entry as observed in the latest run)
   through all later segments.
3. **Write** the predicted exits into the checkpoints of the excluded units that precede a
   run's group, in that run's directory (only the registers the unit modifies).
4. **Verify** after the batch: the exit of every unit whose predicted checkpoint a later run
   used must equal the prediction, and other registers must still pass through. At the first
   mismatch the chain is predicted again from the actual exit; later groups whose start entry
   changes are dirty again, and the glue (its pages come from the last run).

Mispredictions only cost an iteration (e.g. a reference string that changes width).

#### 6.9.4 Cold build

The same loop from an empty `canon/` with all units dirty: a full run, biber and makeindex,
then usually one parallel batch for the units whose references were undefined (their entries
are known from the full run). Cost ≈ one full pass plus parallel passes, instead of a
sequence of full passes.

### 6.10 External tools

**biber** runs with the shadow tree as working directory on `canon/main.bcf`
(`--output-directory canon`; `.bib` paths resolve relative to the working directory).

- **`.bcf` patch** (S5): a partial run's `.bcf` lists only the citations of the glue and its
  units. The `bcf:citekey` elements of a run correspond in order to its `\abx@aux@cite` lines,
  so the main-aux slices attribute them to segments. The canonical list is the concatenation
  in document order of each segment's elements from its committing run, `order` renumbered
  (one number per citation command).
- Datalists are declared where `\printbibliography` runs: the patched `.bcf` gets those of all
  runs of the batch and, unless a run compiled all units, those of the previous canonical
  `.bcf`.
- biber runs when the patched `.bcf` changed or there is no `.bbl`; never on an unpatched
  partial `.bcf`. A run that compiled all units checks the patch against its own `.bcf`
  (§6.14). biber errors are shown with the `.blg` lines.

**makeindex** (nomencl): the canonical `.nlo` is the concatenation of the segments' entries
(split at the `%chapmk-seg` markers); makeindex runs when it changed. Full mode also runs
makeindex for a generic `.idx`, like latexmk.

### 6.11 PDF merge

`merge_pdf.py` (pikepdf), input: per segment in document order its run PDF and page indices.

1. **Pages** are appended in order; a map `(run, page) → merged page` is kept.
2. **Named destinations:** each run contributes the names whose target page was taken from it
   and that are not dummies (dummies are listed in the run log, S6). Duplicate names: the
   first in merged page order wins, as pdfTeX keeps the first definition. A name no run
   defines gets pdfTeX's dummy (first page, `/Fit`); a name defined only on pages not taken is
   an error (fallback).
3. **Links** keep their named destinations; direct page references are remapped.
4. **Outline** from the `\BKM@entry` records of the canonical main aux with the levels of
   `\chapmk@bkmlevels`: parent = nearest previous entry of lower level (bookmark's rule),
   `/Count` from the open state.
5. **Page labels** from the page map (`\c@page` and `\thepage`), styles inferred (arabic,
   roman, Roman, alph, Alph, else a prefix).
6. **Catalog and info:** all catalog entries except those rebuilt above, with page
   references mapped (`/OpenAction`, `\pdfcatalog` entries, S13), and the document info,
   from the run of the first merged page (`G0` has no pages when the document starts with an
   `\include`, and its run may not have compiled the first unit). pdfTeX refers to pages by
   number (`openaction goto page 1`): page N of that run must be page N of the merged PDF,
   otherwise a merge error (full mode).
7. **Font descriptors** are normalised to the whole-document rule (§6.17).

The merged PDF is larger than a plain one (font subsets per run); `--full` gives the compact
file.

### 6.12 SyncTeX merge

`synctex.py` (S10). Line numbers need no mapping (§6.2), only paths and numbers:

1. Each run's SyncTeX file is read once, and only the sheets of its taken pages are kept
   (whole-text regular expressions; this step dominates the merge time on large documents).
2. Input tags are renumbered globally in the order of their first use, each `(run, tag)`
   mapped once; the paths are mapped: run main → user's main file, shadow tree → source
   directory, keeping TeX Live's `<cwd>/./<relative>` form, which `synctex view` needs for
   relative names (MiKTeX has no `/./`, §6.16). Tag 0 (no input file, form xobjects) stays.
3. The sheets are renumbered to merged page numbers; the header is copied (equal in all runs,
   else error); the `!` byte offsets and the postamble are recomputed; gzip level 1.

Measured: 319 pages from 5 runs in about 0.35 s.

### 6.13 Logs and errors

- Errors are printed in `file:line: message` form with mapped paths.
- A failing run commits nothing; the previous `main.pdf` is kept; exit code 1; `main.log` is
  the failing run's log with mapped paths (editors parse it).
- On success `main.log` is composed in the order of a plain pdflatex run: chapmk.sty writes a
  marker line (`chapmk-segment: <seg>`, `\wlog`) at the start of every segment and after the
  last page (`end`); `\include`'s `\clearpage` puts each segment's pages and messages between
  its markers. The composed log is the head of the run of `G0` with the preamble part of the
  format build's log after the main file is opened (files still open at the dump closed), each
  segment's slice from the run that produced it (state), and the tail (aux check, summaries)
  of the last glue segment's run, its `Output written on` line replaced by the merged PDF's.
  Messages and their order match a full build; differences: summaries at the end cover the
  last run only, pages of exported pictures appear as extra `[n]`. A run log without markers
  (older chapmk) gives the logs of the runs one after the other, each with a header.
- `--print-log` writes the published `main.log` to stdout after the build, also after a TeX
  error (the failing run's log) and a no-op build. Editors that parse only the output of the
  build command (VS Code LaTeX Workshop) need it; LaTeX Workshop keeps only the text after the
  last `This is pdfTeX, Version` line, so the printed copy keeps that banner line only in the
  first run's log (the file is unchanged). After the log it writes the output of the state's
  last biber run (`biber.out` in `canon/`, in full mode in `full/`; paths mapped), as latexmk's
  output contains it: LaTeX Workshop parses biber's `INFO`/`WARN`/`ERROR` lines from there
  (the `.blg` has a prefix on every line). After a biber failure, that run's output.

### 6.14 Fallbacks to full mode

Full mode: plain sequential runs to a fixpoint in `full/` (like latexmk: rerun while a file read
by a pass changed; biber, makeindex), with `chapmk-ini.sty` and the picture cache, publishing
the PDF, SyncTeX file and log. Triggers:

- unsupported packages, from the preamble and at runtime from the `.fls` of the format build
  and of every run (classes load packages too); hyperref without bookmark;
- biblatex refsections (static) and citations in a refsection other than 0 (runtime);
- `\documentclass` not before the split line;
- a format build failure, including state a format cannot keep (§6.3.3);
- an eqparbox tag shared by chapters whose width changed (§6.9.1);
- primitive marks (§6.4.2);
- missing, truncated or inconsistent records; merge errors;
- no fixpoint after 8 iterations;
- runtime self-checks (C14), which compare chapmk's results with what TeX wrote: a batch with
  a run of all units has the same `.bcf` citations and datalists as the patch; a unit no run
  compiled keeps its list entries; each merged page's label equals its label in its run;
- `--full`.

All are `errors.FallbackError`, handled only by the builder; each is reported as one warning
(`full build: <reason>`). Reasons found at runtime that will recur are persistent
(`canon/full-only.json`, keyed by the main fingerprints and the chapmk version): later builds
go straight to full mode. Any other exception is a bug: exit code 3, one line, the traceback
with `-v` (C9).

### 6.15 CLI and configuration

```
chapmk build [MAIN] [-j N] [--full] [--check] [--report FILE] [--print-log] [--build-dir DIR] [--out-dir DIR] [--keep-runs] [--no-wait] [-v]
chapmk check [MAIN] [build options]           # = build --check
chapmk clean [MAIN] [--no-wait]
chapmk graph [MAIN] [--format text|dot|json]
```

- **Exit codes:** 0 ok; 1 TeX error or `check` difference; 2 other error (configuration,
  missing program, unsupported document); 3 internal error; 130/143 interrupted.
- **Report** (`--report FILE`): JSON with mode, reason, runs (selection, dirty reasons per
  unit, glue reason, tools, TeX time per phase), compiled includes, warnings, hints and the
  wall time per build phase.
- **`check`** builds the `--full` reference into `check/` with the state's epoch and a fresh
  picture cache, then compares (§3.3).
- **`graph`** shows compilation units, glue, global units, imports by exporter and pending
  reasons (`--format dot`: Graphviz).
- **`clean`** removes the build directory, only if it carries the build-directory marker.
- **One process per build directory** (C6): `build`, `check` and `clean` hold an OS file lock
  on `<build>/lock`, released also when the process is killed. A second process waits with a
  message, or fails with `--no-wait`.
- **Signals** (C8): every external program runs in its own process group and is registered;
  on SIGTERM (an editor stopping a build) or SIGINT chapmk kills them all, starts no new ones
  and exits with 143/130. An interrupted commit is caught by the journal (§6.6).
- **Configuration:** `chapmk.toml` next to the main file; keys and defaults in
  `docs/configuration.md`; unknown keys are an error; command-line options override it.

### 6.16 Platforms

All TeX, biber and makeindex command lines and the distribution's path conventions come from
the distribution adapter (`texdist.py`: `TeXLive`, `MiKTeX`, chosen by the `pdflatex
--version` banner).

| Topic | TeX Live | MiKTeX (S11) |
|---|---|---|
| Format use | `-fmt=<name>` via `TEXFORMATS` | `--undump=<absolute path>` (`TEXFORMATS` ignored) |
| Read order | output directory first (S2) | working directory first; the shadow tree covers both |
| Log line length | `max_print_line=10000` (environment) | `--max-print-line=10000` |
| Run main on the command line | bare name via `TEXINPUTS` | path relative to the working directory (a `TEXINPUTS` name becomes absolute and may contain `_`) |
| SyncTeX input paths | `<cwd>/./<rel>`; `synctex view` with relative names | `<cwd>/<rel>`; `synctex view` needs absolute names |
| `.fls` | relative to `PWD` | absolute |
| Missing packages | – | on-the-fly installation must be "always" or "never"; "ask" is refused at startup (it would block parallel runs) |

**OS rules:** `pathlib` internally, forward slashes to TeX; files are read and written as bytes
or UTF-8 with surrogateescape, never in the locale encoding, line endings preserved;
`subprocess` only, no `fork`. Published outputs are written to temporary files and renamed;
on Windows a viewer may lock the PDF: the rename is retried for 2 s, then the file is written
as `main.chapmk.pdf` with a warning. PDF and SyncTeX file are both written first and then
renamed back to back, SyncTeX first (C16).

**Windows performance:** process start-up and on-access virus scanning of many small files
make builds slower. Measured (MiKTeX, the user's thesis, a typo, one run): 12.7 s on NTFS with
Defender, 4.8 s on a Dev Drive, about 3.5 s on Linux. The README recommends a Dev Drive.

### 6.17 Picture cache

Up to 70 % of a unit's TeX time can be spent in pgf/TikZ pictures. For documents that call
`\tikzexternalize`, chapmk makes and reuses the figures itself, and **the result is identical
to a TikZ-externalized build** (S12). Without `\tikzexternalize` pictures stay inline
(embedded pictures cannot be pixel-identical to inline ones).

- **Embedding** with externalize's own code (`\pgfincludeexternalgraphics`); every picture not
  disabled is embedded, side effects (links, `remember picture`, labels) behave as with
  externalize. A picture typeset for export is followed by a restore of the `\count`
  registers it changed, so later pictures see the same state with or without the cache.
- **Export in the same run, without shell escape:** a picture without a cached figure is
  typeset inline and a copy of its box is shipped as an extra page (primitive `\shipout`),
  announced by a log record. The driver cuts it into `<key>.pdf` plus `.dpth`; the merges skip
  extra pages. The run typeset the picture inline, so its unit (or the glue) is compiled once
  more with the figure embedded; full mode adds a pass.
- **Keys** (content-addressed, independent of the run's selection): md5 of the picture code, a
  stamp (format stamp, main fingerprints), the state at the picture start if the code shows
  counters, `\linewidth`, `\hsize`, font, `\baselineskip`, colour; full mode also a digest of
  all label and citation values. Caches: `fig/` (incremental) and `fig-full/` (full mode);
  unreferenced figures are removed.
- **Validity** (stricter than externalize's md5): an exported figure stores its code and the
  values of the label and citation keys it references and the digests of the source files it
  read or names; a change removes the figure before the next batch or pass. A change of the
  distribution files of the exporting runs empties the cache. `check` uses a fresh cache for
  its reference.
- **Font descriptors:** pdfTeX writes the descriptor of a font that also occurs in an included
  PDF with the font file's metrics, otherwise with TFM metrics; runs see only some figures, so
  the merge normalises descriptors to the whole-document rule (text extraction depends on
  them).
- `pictures.cache = false` typesets every picture inline.

---

## 7. Build directory and persistence

```
.chapmk/<jobname>/
  .chapmk-build-dir   marker (clean refuses directories without it)
  lock                build lock (§6.15)
  src/                shadow tree (§6.5)
  fmt/                format: pre.tex, pre.fmt, pre.log, pre.fls, stamp.json (§6.3)
  runs/r<N>/          incremental runs; unreferenced ones are removed (--keep-runs keeps them)
  canon/              canonical state (§6.6): aux, list and tool files, state.json,
                      full-only.json, lint-cache.json, published.json, .in-progress
  full/               full mode (§6.14), .in-progress while passes run
  fig/, fig-full/     picture caches (§6.17)
  check/, check-fig/  reference of chapmk check
```

Persisted files and their keys:

| File | Invalidated by |
|---|---|
| `canon/state.json` | `STATE_VERSION` (any change of its meaning), format stamp, fingerprints, global inputs, distribution files (§6.6) |
| `fmt/stamp.json` | the format stamp (§6.3.1) |
| `canon/full-only.json` | main fingerprints, chapmk version |
| `canon/lint-cache.json` | file content, lint options, chapmk version |
| `fig*/` | keys, references, files, distribution files (§6.17) |
| `canon/published.json` | the state digest and the published files' size and mtime (a no-op build keeps the outputs only if nothing touched them) |

Upgrades (C4): the chapmk version is part of the format stamp and of the other keys, so a new
version never reuses state it might interpret differently.

---

## 8. Testing

Details and commands: `tests/README.md`, `CONTRIBUTING.md`.

### 8.1 Corpus

- `tests/corpus/thesis/`: generated (`generate.py`) from the user's real `scrbook` preamble:
  title page, lists (ToC, LoF, LoT, algorithms, todos), nomenclature, 6 chapters and 2
  appendices via `\include`, bibliography; equations, theorems, figures, tikzpictures,
  subfigures, tables incl. longtable, siunitx, algorithms with eqparbox, listings, citations,
  cross-references of all kinds, todos, a German passage. Variants `twoside`/`oneside`.
- `tests/corpus/hgb/`: a second real-world preamble (`hgbthesis`): a class loading biblatex,
  `underscore`, tcolorbox, a local theme file, a sub-chapter include (A5).
- `tests/corpus/pictures/`: externalized pictures of many kinds.
- `tests/corpus/pgfmanual/`: the pgf/TikZ manual (about 1300 pages, 123 includes): stress test
  and benchmark.
- `tests/corpus/minimal/`: the spike reproducers.

### 8.2 Scenario tests

Each starts from a built state, edits, builds with `--check` (§3.3 against `--full`) and
asserts the compiled units and reasons from the report (`tests/scenarios/`).

| ID | Edit | Expected recompiles |
|---|---|---|
| T1 | typo in ch3 | ch3 only |
| T2 | ch3 gets longer (page count) | ch3; then the later units (parallel with prediction, a tail run without); glue |
| T3 | section renamed that another chapter `\nameref`s | ch2, the importer, glue (ToC) |
| T4 | new citation that renumbers the bibliography | the unit, biber, all citing units, glue |
| T5 | new label referenced from another chapter | exporter, importer |
| T6 | new nomenclature entry | the unit, makeindex, glue |
| T7 | longtable rows added | the unit until its self data is stable |
| T8 | algorithm comment width change | that unit (eqparbox) |
| T9 | new figure | the unit; glue (LoF); later units (hyperref's link counter) |
| T10 | page parity change | misprediction path; correct output |
| T11 | `\appendix` moved in the main file | all (cold) |
| T12a/b | preamble edit after / before the split | all; format rebuilt for b |
| T13 | new `\include` | all (cold) |
| T14 | syntax error | exit 1, previous PDF kept, error at `ch4.tex:<line>` |
| T15 | `\section*` in several units | no extra duplicate destinations; links resolve |
| T16 | cold build | §3.3 |
| T17 | SyncTeX round trip | §3.3 item 4 |
| T18/T18b | `\setlength` in a unit body / inside a group | lint warning, global unit / no hit |
| T19/T19b | stale build files in the source directory; alternating latexmk and chapmk | ignored; both correct |
| T20 | a chapter split into two includes | one compilation unit; running heads correct |

Further scenarios cover the review's robustness and edge cases (`test_edge_cases.py`,
`test_robustness.py`: local packages, list files of other packages, upgrades, running heads,
primitive marks, shared eqparbox tags, format state, interrupted commits, tool errors) and the
picture cache (`test_picture_cache.py`).

### 8.3 Unit, property and acceptance tests

Unit tests without TeX for every parser and pure module (aux statements, records, deps, dirty
rules, scheduling, prediction, `.bcf` patch, page labels, SyncTeX serialisation, …), property
tests (hypothesis) for the text and file round trips, and acceptance tests comparing `--full`
with latexmk on the corpus.

Slow tests check assumptions about TeX and package internals directly
(`tests/slow/test_tex_compat.py`, e.g. how pgf loads its libraries). Weekly workflows
(`.github/workflows/texlive-*.yml`, `miktex-current.yml`) run the suite on the frozen TeX Live releases since 2025
(the oldest supported LaTeX kernel is 2025-11-01), the current TeX Live and the current
MiKTeX, and write the tested versions into their summaries.

### 8.4 Benchmarks

`tests/bench/` (manual): T1, T2, T4, T16 against latexmk with `-j 1` and `-j N`, with the time
per build phase; numbers in `docs/bench.md`.

---

## 9. Status and future work

Implemented: everything above (release 0.9). History: `CHANGELOG.md`, spike notes, review.

Open:
- Windows and macOS in CI (TeX Live), Windows with MiKTeX beyond the manual workflow.
- `chapmk watch` (F8).
- Usability items of the review (report on failure and a versioned report schema, U3/E6;
  `.bib` edits without a cold build, U8).

Candidates for later:
- a content-addressed unit cache (CI, fresh checkouts);
- skippable glue (checkpoints for glue without macro effects);
- a speculative parallel first pass of a cold build;
- the hyperref `.out` outline route;
- sources outside the main file's directory (configurable shadow-tree root);
- BibTeX backends;
- restoring state a format loses instead of falling back (`cmap`, colour stacks);
- relocatable build directories.

---

## 10. Limitations and risks

| Limitation or risk | Handling |
|---|---|
| Partial-run differences not captured by the `\count` vector (dimensions, skips, `\everypar`, …) | Acceptance and scenario tests; `chapmk check`; extend the vector if needed |
| Label or citation keys built by macros, references hidden in macros inside pictures | Not tracked; `chapmk check` detects |
| Glue cost in every run (bibliography, lists) | Slow-glue hints (§6.8.4) |
| Larger merged PDF | `--full` for the final version |
| One of TeX's 16 write streams used by chapmk.sty | Documented |
| Dates fixed at the cold build (N4) | Documented; `chapmk clean` for a new date |
| PDF features without merge rules (forms, optional content) | Catalog entries are copied with mapped page references; `check` compares the catalog |

---

## Appendix A — Reference preamble

The user's `scrbook` thesis preamble (the thesis corpus): class with `draft` and `twoside`,
babel, biblatex, nomencl, xcolor, pgf, gnuplot-lua-tikz, algorithmic, listings, eqparbox,
`hyperref` and `bookmark` (both in the format, S1), `\makenomenclature` (replayed, S1), and an
`\ifdraft{\tikzexternalize …}` block where the split point lies (the start of the group, S1).
Relevant mechanisms: the `.nlo` stream, biblatex renumbering, longtable and eqparbox self data,
`section*` anchors, the bookmark outline, `\listoftodos`, the `loalg` list, odd chapter starts.

## Appendix B — Record formats (written by `chapmk.sty`)

| Record | File | Format |
|---|---|---|
| baseline | main aux | `\chapmk@base{n=v,n=v,...}` (state vector, §6.4.2) |
| entry | main aux | `\chapmk@entry{<seg>}{n=v,...}` (sparse vs baseline) |
| glue exit | main aux | `\chapmk@gexit{<seg>}{n=v,...}` (sparse vs baseline) |
| absolute set | unit aux / main aux | `\chapmk@abs{<seg>}{n,n,...}` |
| unit checkpoint | unit aux | `\chapmk@ckpt{U<k>}{n=v,...}` (complete vector at the unit's end) |
| unit name | main aux | `\chapmk@unit{U<k>}{<path>}` (empty for an excluded unit without checkpoint) |
| bookmark levels | main aux | `\chapmk@bkmlevels{<id>=<level>,...}` |
| counters | main aux, header | `\chapmk@counters{<name>=<register>:<child>/<child>/;...}` (reset lists) |
| layout | main aux, header | `\chapmk@layout{twoside=0\|1,openright=0\|1}` |
| unit marks | unit aux | `\chapmk@mk{<pseudo register>}{<class>}{<region>_<top\|first\|last>}{<text>}` |
| unit start | unit aux, first statement | `\chapmk@ustart{U<k>}` (writes the list-file start marker) |
| page map | `.frec` | `P <shipout#> <seg> <\c@page> <\thepage text>` |
| file attribution | `.frec` | `F <seg> <path>` |
| elapsed time | `.frec` | `T <point> <\pdfelapsedtime>`: `load`, `begin`, segment ids, `end`, `picture+`/`picture-` |
| eqparbox use | `.frec` | `Q <seg> <tag>` |
| list file | `.frec` | `L <ext>` per `\@starttoc` |
| unit layout | `.frec` | `O <seg> 0\|1` (twoside and openright at the unit start) |
| mark classes | `.frec` | `K <pseudo register> <class>`; `K primitive <n>` |
| stream marker | `.nlo` | `%chapmk-seg <seg>` |
| list-file markers | list files | `\chapmk@lmark{U<k>}`, `\chapmk@lmark{/<seg>}` |

Segment ids: `G0..Gn` for glue, `U1..Un` for units (`segment.py`). The driver checks the
`\chapmk@unit` records against the include order of the analysis.

## Appendix C — Section numbers of the former plan

Sections 1–6 and 8 have the same numbers as in `PLAN.md`. Other references:

| PLAN.md | Here |
|---|---|
| §0 Instructions for the implementing agent | `CLAUDE.md`, `CONTRIBUTING.md` |
| §7 Repository layout | `src/chapmk/CLAUDE.md`; §7 is now the build directory |
| §8.3 Unit tests | §8.3 (with property and acceptance tests) |
| §9 Milestones | §9 Status and future work; history in `CHANGELOG.md` |
| §10 Risks and open questions | §10 Limitations and risks; phase-2 candidates in §9 |
| Appendix A, B | Appendix A, B |
