# Correctness cases (corpus sweeps)

Re-run on `main` `fc71b5b` (after PR 66). Cold incremental builds that fail `--check` (§3.3 against chapmk's own full build) and
full builds that differ from latexmk. Documents are public GitHub repositories at the
pinned commit; `variant`: the sweep's robustness changes (see `sweep.py`: fontspec setup
commented out, `bookmark` added, BibTeX replaced by biblatex). Reproduce with
`sweep.py --variant --latexmk <manifest> <out> <id>`.

## From `manifest3.json`

### [saomyaraj/Prometheus](https://github.com/saomyaraj/Prometheus) `05112d4fda10` (passes on `main` `fc71b5b`)

- main file: `docs/Thesis/mythesis.tex`, class `book`, variant: none
- cold build: cold / PASS (reason: no previous state)
- typo build: incremental / PASS
- full build vs latexmk: PASS

### [LarsNau/Bachelor_Arbeit](https://github.com/LarsNau/Bachelor_Arbeit) `7a29b8e7cab9`

- main file: `LS7-Abschlussarbeit.tex`, class `scrbook`, variant: bookmark
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS outline items: #36: reference (0, 'Abbildungsverzeichnis', 0, (58, '/FitV', (99.213,))) != (0, 'Abbildungsverzeichnis', 0, (0, '/FitV', (99.213,)))`
  - `DIFFERS links: #33: reference (3, (69.87, 594.884, 190.576, 607.493), (58, '/FitV', (99.213,))) != (3, (69.87, 594.884, 190.576, 607.493), (0, '/FitV', (99.213,)))`
- full build vs latexmk: PASS

### [tscheffl/ThinkC](https://github.com/tscheffl/ThinkC) `41694de380f4`

- main file: `Main.tex`, class `book`, variant: bookmark
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS raster pages: #0: reference 'fe4e937be85f3d11744fd8f66e7f958fe4fd38600de1070533a5ff81cced40b8' != '0b51069ba9ea5df07b2ab571a7486e4b77bacb14a0cfb92af85dc2f08cdfc926'`
  - `DIFFERS synctex records: #25: reference '1|(Main.tex,179:9472572,25412898:22609920,928641,264370' != '1|(Main.tex,179:9472572,25347362:22609920,928641,264370'`
- full build vs latexmk: PASS

### [ary1002/triage-learning-medical-diagnosis](https://github.com/ary1002/triage-learning-medical-diagnosis) `c7c498fa14c4`

- main file: `final_report/main.tex`, class `report`, variant: bookmark
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS raster pages: #0: reference '365d1bf457dd6db81164c899308400cacb712f343abae5070a35324e1df6180d' != '79d349e9d5fcdde07aa16f50f1c57ac4b4cfaad9fb23d5c9715928321feae547'`
  - `DIFFERS text pages: #29: reference '                                                Chapter 2. REVIEW OF LITERATURE\n\n\n2.4     Model Interpretability and Explainability\n\n2.4.1    Gradient-Based Sa`
  - `DIFFERS synctex records: #22: reference '1|(main.tex,127:7104430,9892238:27317560,929307,264291' != '1|(main.tex,127:7104430,9642260:27317560,929307,264291'`
- full build vs latexmk: PASS

### [AleksyMieki/Praca-dyplomowa](https://github.com/AleksyMieki/Praca-dyplomowa) `0eb86142af1b`

- main file: `DyplomSzablonMemoirUTF8/Dyplom.tex`, class `memoir`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS catalog entries: #0: reference ('/Metadata', ('stream', '90e5df75c487cfe1fe347b41e5cd9ae6e1fa91b5cddc90bc9a944987628b88a2')) != ('/Metadata', ('stream', 'b5c1922c748e535d4e186d70217dd9593a8654`
- full build vs latexmk: PASS

### [6ym6n/PFE_IMPLEMTATION](https://github.com/6ym6n/PFE_IMPLEMTATION) `8d82fa7dd270`

- main file: `smart-visit-thesis-latex-aligned/main.tex`, class `book`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS links: #127: reference (8, (88.563, 463.852, 524.272, 477.799), (34, '/XYZ', (207.421, 4152.697, None))) != (8, (88.563, 463.852, 524.272, 477.799), (34, '/XYZ', (207.558, 4152.697, None)))`
  - `DIFFERS synctex records: #45736: reference '35|)' != '35|gfigures/fig-taxonomy.tex,83:81697776,25016439'`
- full build vs latexmk: PASS

### [AprilS21/Dissertation](https://github.com/AprilS21/Dissertation) `00f123f2281f`

- main file: `DissertationPDF/thesis.tex`, class `report`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS raster pages: #3: reference 'd94fe43dc0d4c45534c5ce14296af028e9cab9229c1b8ba02709c30b2c8e0807' != '9196e5e35b6f555af0c0bd06862afe6e9d0cfc7d27e56adddc521ebcf401d8cc'`
  - `DIFFERS text pages: #3: reference 'Contents\n\nAbstract                                                                                     i\n\nAcknowledgments                                        `
  - `DIFFERS page labels: #12: reference '6' != 'vi'`
- full build vs latexmk: PASS

### [tintando/strascico-thesis](https://github.com/tintando/strascico-thesis) `ab3b5f9fa6ea`

- main file: `thesis/thesis.tex`, class `sapthesis`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS raster pages: #22: reference '66e0cba3e1e94c4bcb844444882d44b73dd49a7f02ac75367c79d1d6f9a91ea7' != '7122f2c75b1f1ac644b6aede6ef6451843f4c6301209eca28e790c9aa38e88e6'`
  - `DIFFERS text pages: #39: reference '32                                                         4. Dataset Analysis and Results\n\n\n\n\n      Daily volume = active channels (extensive) × msgs/active c`
- full build vs latexmk: PASS

### [STDE-Book/STDEbook](https://github.com/STDE-Book/STDEbook) `720e324af1e2`

- main file: `book_all.tex`, class `svmono_mod`, variant: bookmark
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS raster pages: #19: reference 'd653cb4018f4aeedb7c29128b8119a750e76d9cfe171900e0180e25151da8d77' != 'f76f90bc63ee54804ef8195dc962e6b307169ac59b4e5e890f999fcbf2ce396e'`
  - `DIFFERS text pages: #20: reference '1.4 Estimation with constrains                                                                          15\n\n1.4.2.1 Minimization of the mean squared error.\n\nWe `
  - `DIFFERS links: #278: reference (79, (507.791, 129.34, 528.962, 140.751), (79, '/XYZ', (313.256, 657.256, None))) != (79, (507.791, 129.34, 528.962, 140.751), (79, '/XYZ', (312.886, 657.256, None)))`
- full build vs latexmk: PASS

### [rkmalaiya/Cognitive-Diagnostic-Knowledge-Tracing](https://github.com/rkmalaiya/Cognitive-Diagnostic-Knowledge-Tracing) `a922e44a0d80`

- main file: `mlbook.tex`, class `krantz`, variant: biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS synctex records: #5493: reference '11|(chapters/model/chap1/chap1.tex,144:16887357,44638988:1931100,416162,131071' != '11|(chapters/model/chap1/chap1.tex,144:16887357,44638988:1931100,416162,1`
- full build vs latexmk: PASS

### [DaBrown95/safe-wiki-dissertation](https://github.com/DaBrown95/safe-wiki-dissertation) `5e8dcb524ed4` (passes on `main` `fc71b5b`)

- main file: `dissertation.tex`, class `l4proj`, variant: none
- cold build: cold / PASS (reason: no previous state)
- typo build: incremental / PASS
- full build vs latexmk: PASS

### [filipjezek/bc-mff](https://github.com/filipjezek/bc-mff) `6e45b190bb0b` (passes on `main` `fc71b5b`)

- main file: `thesis.tex`, class `report`, variant: none
- cold build: full / PASS (reason: biblatex backend 'bibtex': only biber is supported)
- typo build: full / PASS
- full build vs latexmk: PASS

### [JinwenFu001/thesis-template](https://github.com/JinwenFu001/thesis-template) `27174ae46a6e`

- main file: `thesis.tex`, class `mnthesis`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS page count: #0: reference 19 != 18`
  - `DIFFERS raster pages: #5: reference '82bc46a31ddc02d211317e2838ecc2e64d775b7bfdf7058c3d46b2d0bc71c36c' != 'a6c0a430d780b61eb60e30a3fa208ef5abea48b6be9ad1ce9ea60cb4eb69b0c0'`
  - `DIFFERS text pages: #5: reference 'Contents\n\nAcknowledgements                                                                                       i\n\nDedication                                   `
- full build vs latexmk: PASS

## From `manifest4.json`

### [CatoMaior/tesi-magistrale](https://github.com/CatoMaior/tesi-magistrale) `09420699bacc`

- main file: `main.tex`, class `book`, variant: bookmark
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS synctex records: #80224: reference '61|f833:5594039,31123453' != '61|f422:5594039,31123453'`
- full build vs latexmk: PASS

### [frefolli/sigmod](https://github.com/frefolli/sigmod) `b6cb40c6602f`

- main file: `report/main.tex`, class `report`, variant: bookmark
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS synctex records: #23229: reference '14|f181:11654249,44160765' != '14|f67:11654249,44160765'`
- full build vs latexmk: PASS

### [jastka4/engineering-thesis](https://github.com/jastka4/engineering-thesis) `5509c76f1ec6`

- main file: `main.tex`, class `memoir`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS text pages: #20: reference '                                                                                                  3.3. User Interface Design\n\n                   a)               `
- full build vs latexmk: PASS

### [bryancrisso/partiiproject](https://github.com/bryancrisso/partiiproject) `c47906d61a9d`

- main file: `dissertation/dissertation.tex`, class `report`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS synctex records: #21176: reference '22|(diagrams/graph1.tex,12:14748822,5912622:0,0,0' != '22|gdiagrams/graph1.tex,12:14748822,5912622'`
- full build vs latexmk: FAIL
  - `DIFFERS page count: #0: reference 79 != 81`
  - `DIFFERS raster pages: #4: reference '5e37a34cc9cc35170368965dc5c30abcd290868b22e6e589617a46072a58b358' != '10e7a544bca5163c5fee6d00a29dc264f739395963d5a6557cad700670c10e5a'`
  - `DIFFERS text pages: #4: reference 'List of Figures\n\n 1.1   Dynamic dependency graph example [ddg] . . . . . . . . . . . . . . . . . . 15\n\n\n 3.1   Partially unrolled cksum loop body in Arm Assembl`
- note: latexmk's List of Figures shows the unresolved key `[ddg]` of a citation in a caption, chapmk's `[1]`; 79 vs 81 pages. Possibly latexmk stopping one run early; not checked.

### [Rajrup/Thesis](https://github.com/Rajrup/Thesis) `7c70be484714`

- main file: `main.tex`, class `report`, variant: bookmark
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS text pages: #36: reference 'Avg. Color RMSE                                                                                          Avg. Depth RMSE\n                  102                     `
- full build vs latexmk: PASS

### [LuckeeDev/bachelor-thesis](https://github.com/LuckeeDev/bachelor-thesis) `be399132a1c2`

- main file: `tex/thesis.tex`, class `report`, variant: bookmark
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS raster pages: #4: reference '0b13bee8b012d6ba8b11f5d180f6973261d0777cf5ea30fb40df6ab2bc6200ed' != '5d6a902a8a184dddf5cf62e513b3904e0d6e0096acbb7c0337180a5afb3eea28'`
- full build vs latexmk: PASS

### [albertopasqualetto/Master-thesis](https://github.com/albertopasqualetto/Master-thesis) `1e49b4910c95`

- main file: `main.tex`, class `unipd-thesis-modern`, variant: bookmark
- cold build: full / PASS (reason: format build failed: ./docs/glossary.tex:5: Paragraph ended before \openout was complete.)
- full build vs latexmk: FAIL
  - `DIFFERS raster pages: #0: reference '14a465a4877ab38d3dbf085b82696f5c880eccd8e2176afc9dec5bc073dea8f9' != '4916dd0925ed27774063f869a8c60c910bfc38798293bc620eaad89d5f7e7849'`
  - `DIFFERS text pages: #2: reference '    Contents\n\nAbstract                                                                                       v\n  Sommario . . . . . . . . . . . . . . . . . . . . `
  - `DIFFERS outline items: #5: reference (0, 'I Theoretical Foundations', -2, (11, '/XYZ', (70.866, 319.087, None))) != (0, 'I Theoretical Foundations', -2, (11, '/XYZ', (70.866, 304.193, None)))`
- note: latexmk used the repository's `.latexmkrc` (LuaLaTeX): harness error, `sweep.py` now passes `-norc`; chapmk's format build fails (`docs/glossary.tex:5`), full mode, `--check` passes.

## From `manifest5.json`

### [Agda78/APC-appunti](https://github.com/Agda78/APC-appunti) `d18fd38cb077`

- main file: `main.tex`, class `extbook`, variant: bookmark
- cold build: cold / PASS (reason: no previous state)
- typo build: incremental / FAIL
  - `DIFFERS text pages: #74: reference 'Ovvero, la somma tra il tempo di esecuzione di una parte del programma che è stretta-\nmente seriale e il tempo di esecuzione della parte del programma che è parall`
- full build vs latexmk: PASS
- note: font descriptor metrics (see se-tuebingen); here the full build itself has zeros for `LMRoman12-Italic` and other values for `LMRoman12-Bold`.

### [raktim-mondol/neural-operator](https://github.com/raktim-mondol/neural-operator) `95c283781499`

- main file: `Neural_Operator_Book.tex`, class `book`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS raster pages: #39: reference '22169fa865b293a0d36f3b0c09f14e28da77002791f5628f02ec55db711c7897' != '6c52b1f7940bdc110d2ca9cdcf1dff129b7cb6298f55b0e8e4cdc009c5d5342e'`
  - `DIFFERS text pages: #69: reference 'The Fourier Neural Operator: Spectral Theory and Convergence\n\n\nThe middle step uses |k| ≥ maxi |k i | > kmax for every discarded mode k ∈\n                      `
  - `DIFFERS links: #616: reference (36, (313.426, 305.412, 329.055, 317.583), (79, '/XYZ', (166.537, 160.069, None))) != (36, (313.426, 305.412, 329.055, 317.583), (79, '/XYZ', (166.715, 160.069, None)))`
- full build vs latexmk: PASS

### [rohith-0099/nemotron3-super-seminar-report](https://github.com/rohith-0099/nemotron3-super-seminar-report) `96bfa77ba1c0`

- main file: `report/main.tex`, class `report`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS text pages: #13: reference ' 2.2                 Hybrid Mamba–Transformer Models\nIf Mamba is efficient but forgetful and attention is precise but expensive, the natural step is to\nmix them. `
- full build vs latexmk: PASS

### [se-tuebingen/thesis-template](https://github.com/se-tuebingen/thesis-template) `de35a5f25ac3`

- main file: `thesis.tex`, class `report`, variant: bookmark
- cold build: cold / PASS (reason: no previous state)
- typo build: incremental / FAIL
  - `DIFFERS text pages: #10: reference 'Chapter 1\n\nImportant first chapter                                                               Replace this placeholder title\n                                 `
- full build vs latexmk: PASS
- note: font descriptor metrics: pdfTeX takes Ascent, CapHeight, Descent from one instance of the font (apparently the one first used last: LIFO font list); run r4 (ch1 excluded) used a TS1-like instance (zeros), the full build a T1 one (471/653/-3). The merge copies the first page's run values. Rendering identical, only pdftotext's word boxes differ. A fallback on disagreement made the hgb corpus full on every edit; left open (user decision).

### [sprakash1612/triage-learning-medical](https://github.com/sprakash1612/triage-learning-medical) `55c7795a555e`

- main file: `final_report/main.tex`, class `report`, variant: bookmark
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS raster pages: #0: reference '365d1bf457dd6db81164c899308400cacb712f343abae5070a35324e1df6180d' != '79d349e9d5fcdde07aa16f50f1c57ac4b4cfaad9fb23d5c9715928321feae547'`
  - `DIFFERS text pages: #29: reference '                                                Chapter 2. REVIEW OF LITERATURE\n\n\n2.4     Model Interpretability and Explainability\n\n2.4.1    Gradient-Based Sa`
  - `DIFFERS synctex records: #22: reference '1|(main.tex,127:7104430,9892238:27317560,929307,264291' != '1|(main.tex,127:7104430,9642260:27317560,929307,264291'`
- full build vs latexmk: PASS
- note: the same document as ary1002/triage-learning-medical-diagnosis (same differences).

## From `manifest6.json`

### [alorenzo175/dissertation](https://github.com/alorenzo175/dissertation) `bd0a7840750e`

- main file: `dissertation/dissertation.tex`, class `uathesis`, variant: bookmark, biblatex
- cold build: cold / FAIL (reason: no previous state)
  - `DIFFERS raster pages: #0: reference 'acf2c6d6e3d3ea93fa391c627e0df14527c7a763bfc56b3b83655139153cbd27' != '1773eff3a8f7df26ae26deae8efc46ded288dbaacb3e4f14b2c61b29c5d37e26'`
  - `DIFFERS text pages: #19: reference '                                                                                            20\n\n\n                          Forecast Horizon for Various Forecast `
  - `DIFFERS outline items: #46: reference (0, 'REFERENCES', 0, (123, '/XYZ', (108.0, 393.755, None))) != (0, 'REFERENCES', 0, (115, '/XYZ', (108.0, 684.0, None)))`
- full build vs latexmk: PASS

## Full-mode fallbacks worth a look (sweep 5, correct output)

- [BernhardMarconato/computer-vision-exercises](https://github.com/BernhardMarconato/computer-vision-exercises) (`project_1_scanner/documentation`): `unreadable records (invalid literal for int() with base 10: 'er {abspage}\pp@cl@end ')`: perpage (`footmisc[perpage]`, `\c@pabs@page` is a macro); perpage unsupported now (PR).
- [BartlomiejKufel/projekt-bazy-danych](https://github.com/BartlomiejKufel/projekt-bazy-danych): `.bcf has 1 citekeys, the aux 0 citations`; the next build then reports `the previous build was interrupted while committing` (the journal a fallback inside the commit leaves, C7), which reads like a crash; message fixed (PR).

## Earlier cases

- [rimrim/thesis](https://github.com/rimrim/thesis) (`manifest2.json`): full build vs
  latexmk differs in one SyncTeX record (page 50, a `description` item box in
  `chapter2.tex:915` shifted by 24379 sp); pixels and text identical. Open.
- Fixed: babel-spanish roman page labels (PR 64), `\include{./x}` and `\include{x.tex}`
  (PR 63), page labels without hyperref (PR 65), `.bcf` self-check numbering and an
  `\include` in a class macro (PR 66).
