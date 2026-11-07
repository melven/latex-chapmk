# Correctness cases by category (sweeps 2–7)

All 33 cases re-run on `main` `59f74a7` (`rerun.jsonl`); failing cold builds rebuilt fresh and
compared in full against the `--check` reference (`analysis.jsonl`). 3 cases pass now
(Prometheus, DaBrown95, bc-mff), rimrim's latexmk difference is gone (full mode: BibTeX).
A document can be in several categories.

## A. Font descriptor metrics (text extraction only; rendering identical)

- **A1. Fonts of included PDF figures (merge bug).** `merge_pdf._normalize_font_descriptors`
  rewrites the descriptor of every font that occurs in a figure to the FontBBox rule; pdfTeX
  keeps the figure's own values for fonts it does not replace (e.g. `ArialMT`: reference
  905/716/-212, merged 1039/1039/-325). tscheffl, tintando, STDE-Book, CatoMaior, jastka4,
  Rajrup, raktim-mondol, rohith-0099, alorenzo175, KubeCloud (10).
- **A2. TFM metrics from different font instances** (left open, user decision): ary1002 =
  sprakash1612, 6ym6n, wvianna, ascalva, se-tuebingen, Agda78 (6).

## B. Page content (raster)

- **B1. First page shifted vertically** (title page in the glue before the first include;
  SyncTeX y on page 1: 1 pt, 3.8 pt, 4.7 pt): tscheffl, ary1002, alorenzo175 (3).
- **B2. One page's pixels differ** (cause unknown): LuckeeDev p5, wvianna p18, tintando p23,
  STDE-Book p20, raktim-mondol p40 (5).
- **B3. Front matter: ToC page, page labels, page count**: AprilS21 (ToC, label `6` vs `vi`),
  JinwenFu001 (19 vs 18 pages, labels, outline, all 21 links missing) (2).

## C. Destinations and links

- **C1. Destination on the wrong page**: LarsNau (`/FitV` to page 1 instead of 59),
  alorenzo175 (REFERENCES page 116 vs 124) (2).
- **C2. Destination x shifted < 0.4 pt** (`/XYZ`): 6ym6n, STDE-Book, raktim-mondol (3).

## D. Catalog

- **D1. `/Metadata` stream differs** (XMP; both Polish "Praca dyplomowa" templates):
  AleksyMieki, Joaszek (2).

## E. SyncTeX only

- **E1. Form references `f<n>`** (xform numbers differ): CatoMaior, frefolli (2).
- **E2. `(` box vs `g` record for figure files** (picture cache): bryancrisso, ascalva,
  6ym6n (3).
- **E3. Box dimension** (depth 131071 vs 134633): rkmalaiya (1).

## F. chapmk `--full` vs latexmk

- bryancrisso, JulianVidal/AGDA_HTML: chapmk 2 pages more; latexmk's List of Figures has an
  unresolved citation (`[ddg]`): latexmk probably stops one run early (not checked).
- albertopasqualetto: links (format build fails, full mode).
- CodingLangur/Finch.ai: one `synctex edit` lookup in `main.toc`.
