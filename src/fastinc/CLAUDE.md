# src/fastinc: module map for agents

Read this before adding code. Reuse the listed functions instead of writing new ones.
**Keep this file in sync**: every new or removed module or public function and every changed
responsibility is updated here in the same commit.

## Layering (imports only go downwards)

```
cli                       command line, exit codes
incremental, graph        builder: full mode or the fixpoint loop (cold / incremental / noop); graph
outputs                   merged PDF, SyncTeX, log of the canonical state
canon                     canonical files: read views, commit of a run (incl. biber, makeindex)
merge_pdf, state          PDF merge, canonical state (state.json)
fullbuild                 full-mode build; converge() fixpoint loop of full mode
deps, tools, lint         dependency model (imports), biber/makeindex inputs, A1 lint
runner, records           incremental runs (run directories, parallel pool), record parsing
fmt                       format build
check                     §3.3 comparison (pikepdf, poppler, synctex CLI)
shadow, layout, gensrc    shadow tree, directory layout, generated TeX sources
analysis                  static analysis of the sources
texdist, proc             TeX distribution adapter, subprocess helper
aux, synctex, publish, logs  file formats and output handling
texsource, config, errors basics
```

## Modules

| Module | Purpose (PLAN §) | Public API |
|---|---|---|
| `errors.py` | Exceptions; `str(err)` is the user message; `exit_code` 2 (1 for `TexError`) | `FastincError`, `ConfigError`, `AnalysisError`, `ToolError`, `TexError(msg, log, first_error)` |
| `config.py` | `fastinc.toml` plus CLI overrides (§6.15) | `Config` (frozen; `effective_jobs`), `load_config(main, cwd, **overrides)`, `parse_config_file(path)`, `find_config_file(dir)`, `CONFIG_NAME` |
| `texsource.py` | Scanning TeX source without TeX: comments, braces, control words, arguments | `split_lines` (at `\n` only; never use `str.splitlines`), `strip_comment(s)`, `control_sequences`, `find_macros(text, names) -> [Macro]`, `read_group`, `read_optional`, `skip_space`, `LineIndex`, `depth_at_line_starts`, `split_list` |
| `analysis.py` | §6.1: `\begin{document}`, inlined preamble inputs, format split point, includes, compilation units (A5), fingerprints, fallback reasons | `analyse(config) -> Analysis`; `Analysis` (`lines`, `begin_line`, `split_line`, `split_reason`, `includes`, `units`, `fingerprints`, `fallback_reasons`, `warnings`, `jobname`, `newline`), `Include` (`heading`, `resets`), `CompilationUnit`, `Fingerprints`, `read_source`/`encode_source` (exact byte round trip), `DENY_SPLIT`, `UNIT_HEADINGS`, `UNSUPPORTED_PACKAGES` |
| `gensrc.py` | §6.2: generated sources that keep line numbers | `format_source(a)`, `run_main(a, selection, deny_names)` (`None` = all units, `[]` = glue only; `deny_names` = extra run-local registers for fastinc.sty), `full_mode_input(a)`, `write_if_changed(path, text)`, `INI_PACKAGE`, `RUNTIME_PACKAGE` |
| `proc.py` | Run programs: argv only, stdin closed, combined output | `run(argv, cwd=, env=, timeout=, log_path=) -> ProcResult` (`ok`, `output`, `seconds`) |
| `texdist.py` | §6.16 distribution adapter. **Only place with engine flags.** | `detect() -> TexDistribution`, `TeXLive` (`pdflatex`, `format_build`, `biber`, `makeindex` (style None: default), `environment`, `version`, `check_tools`), `deterministic_env(epoch)` (N4), `tex_path`, `TEX_DIR` |
| `layout.py` | Build directory parts and published outputs | `Layout` (`shadow_dir`, `fmt_dir`, `full_dir`, `runs_dir`, `canon_dir`, `output(suffix)`, `path_map()`), `make_layout(config, analysis)` |
| `shadow.py` | §6.5/S2 shadow tree (symlinks, build outputs excluded, refresh) | `sync_project_shadow(a, shadow_dir, build_dir)`, `sync_shadow(...)`, `build_output_filter(a)`, `ShadowStats` |
| `fmt.py` | §6.3 format build, reused while the stamp matches | `ensure_format(a, layout, dist, env) -> FormatInfo`, `format_stamp(a, version)` |
| `logs.py` | §6.13 log helpers | `map_paths(text, mapping)`, `first_error(log)` |
| `synctex.py` | §6.12/S10 SyncTeX files: read, write with recomputed `!` offsets, path mapping (keeps `/./`), merge of several runs | `read_lines`, `write_lines`, `serialise`, `map_input_paths`, `rewrite_paths`, `parse(path) -> ParsedSyncTex`, `merge(pages, map_path, out)`, `SyncTexError` |
| `publish.py` | Atomic output replacement with Windows retry and `.fastinc` fallback name | `publish(write, target) -> Path`, `copy_bytes(src)`, `text_writer(text)` |
| `runner.py` | §6.5 run directories and the parallel pool (threads waiting on subprocesses) | `RunSpec(name, selection)`, `RunResult`, `prepare_run_dir(a, layout, spec, canon_dir=, deny_names=)`, `run_one(...)`, `run_batch(a, layout, dist, env, specs, fmt_name, jobs)`, `RUN_MAIN` (fixed run-main name, found via `TEXINPUTS`), `DERIVED_SUFFIXES` |
| `records.py` | Parse fastinc.sty records (Appendix B) from a run directory | `read_run_records(run_dir, a) -> RunRecords` (`base`, `entries`, `glue_exits`, `absolute`, `units`, `checkpoints`, `bookmark_levels`, `pages`, `files`, `nomenclature`, `counters`, `segments_in_order()`, `entry_state(seg)`, `reset_registers(counter)`), `parse_counters`, `register_names(logs)`, `read_nomenclature(nlo)`, `PageRecord`, `parse_vector`, `parse_indices`, `RecordError` |
| `fullbuild.py` | §6.14 full mode and the fixpoint loop | `full_build(a, layout, dist, env, report=) -> FullBuildResult`, `converge(job, outdir, cwd, dist, env, run_pass, ...)` (rerun while a build file read by a pass changed; biber, makeindex for `.nlo` and `.idx` via `run_tools`), `PassResult`, `ToolState`, `read_inputs(fls, cwd, within)` |
| `aux.py` | §6.7 aux helpers (no Python list-file linker: TeX writes .toc etc. itself) | `statements(lines)` (brace-balanced), `classify(stmt)` → class constants (`LABEL`, `LIST`, `CITE`, `BACKREF`, `BIBDATA`, `SELF`, `EQP`, `AGGREGATE`, `LISTDATA`, `GLOBAL`, ...; `UNIT_CONTENT`), `statement_key`, `normalize_statement` (drops biblatex instcount), `run_input_main_aux(stmts, excluded)`, `command_name`, `segment_of_statements`, `canonical_main_aux(run, old, keep_old, aggregates, pages)`, `segment_slices(main_aux_lines)` (per-segment main-aux lines, S5/S8), `content_lines` (drop `\relax`/`\providecommand`), `parse_bookmark(line) -> Bookmark`, `bookmark_levels(lines)`, `tex_octal_bytes`, `read_lines` |
| `deps.py` | §6.8 imports: text scan of sources for label/cite keys, key values (`L:`/`C:` namespaced short hashes) | `label_values(aux_statement_lists)`, `defined_labels(stmts)`, `cite_values(bbl, aux_statements)` (`.bbl` block + position + keyed `\abx@aux@*` data), `TokenScan(texts)` (`references(key)`, `reads_lists()`), `imports(scan, values)`, `changed_imports(stored, scan, values)`, `read_text(path)` (None for binary), `short_hash`, `UNDEFINED` |
| `tools.py` | §6.10 tool inputs on the canonical state: `.bcf` citekeys per segment and patch, canonical `.nlo` | `citekey_lines(bcf)`, `citations_by_segment(main_aux_lines, bcf)`, `patch_bcf(bcf, [(segment, element)])`, `nomenclature_file(segments, entries)`, `ToolInputError` |
| `lint.py` | §6.8.4 lint (A1): local commands outside explicit groups, global commands anywhere | `lint_text(text, file, allow) -> [LintHit]` (`file`, `line`, `command`, `is_global`, `message()`), `lint_files(source_dir, names, allow)` (TeX sources only), `LOCAL_COMMANDS`, `GLOBAL_COMMANDS` |
| `state.py` | §6.6 canonical state `<build>/canon/state.json` (version 2) | `State` (`epoch`, `fingerprints`, `format_stamp`, `includes`, `segments: {seg: SegmentArtifact(run, pages)}`, `segment_files`, `global_files`, `next_run`, `units: {seg: UnitInputs(entry, imports, lists, self_stable)}`, `citations`, `aggregates`, `glue_inputs`, `pending`, `glue_pending`, `run_names()`, `new_run_name()`), `load_state`, `save_state` |
| `merge_pdf.py` | §6.11/S9 merge: pages, named destinations (first wins, dummies dropped, names undefined everywhere get pdfTeX's dummy), outline from bookmark records, page labels, catalog | `merge_pdf(pages, outline, catalog_from, out)`, `PageSource`, `OutlineEntry`, `page_labels`, `label_style`, `dummy_destinations(log)`, `MergeError` |
| `incremental.py` | Builder (M4, §6.9): full mode for fallback reasons; otherwise `Fixpoint`: one run per iteration with the dirty compilation units plus glue, commit, dirty rules (sources, imports, self, entry + tail run, global units in every run, eqparbox/aggregates/unclassified aux data, list readers), glue validity; cold build = the loop from an empty canon; max 8 runs then full mode; run GC | `build(ctx, epoch, full=) -> BuildReport`, `Context`, `BuildReport` (`mode`, `reason`, `runs` [name, selection, reasons, glue, tools, seconds], `compiled`, `warnings`, `to_json()`), `Fixpoint` (`initial`, `plan`, `run`, `after_run`, `converge`), `load_epoch`, `FallbackError` (`persistent`), `MAX_ITERATIONS` |
| `canon.py` | §6.6/§6.7/§6.10 canonical files: `CanonView` (main/unit aux statements, key values, list hash; `unit_self`, `glue_data`, `of_class`, `eqp`), commit of a run (unit aux, pages, canonical main aux, list files, `.bcf` patch + biber in canon, `.nlo` + makeindex) | `read_canon(analysis, canon_dir)`, `commit_run(analysis, layout, dist, env, state, run, recs, compiled) -> tools`, `segments(analysis)`, `LIST_SUFFIXES` |
| `outputs.py` | §6.11–6.13 published outputs of the canonical state; failed-run log | `publish_state(analysis, layout, state) -> pdf`, `failed_run(analysis, layout, run_dir, err)`, `map_run_paths`, `MergeFailedError` |
| `graph.py` | `fastinc graph`: compilation units, attributed files, imports by exporter, lint (global), pending reasons | `dependency_graph(analysis, layout, allow) -> Graph` (`IncludeNode`), `to_text`, `to_dot`, `to_json` |
| `check.py` | §3.3 comparison of two builds | `compare_pdfs(ref, got) -> Report`, `compare_synctex(ref, got, sources, cwd)`, `Report` (`ok`, `differences`, `counts`, `summary()`) |
| `cli.py` | `fastinc build [--full] [--check] [--report FILE]`, `fastinc check`, `fastinc clean` (only directories with `BUILD_DIR_MARKER`), `fastinc graph [--format text\|dot\|json]` | `main(argv, cwd) -> int` |
| `tex/` | LaTeX packages, see `tex/CLAUDE.md` | |

## Invariants

- Never write into the source directory except the published outputs (`<jobname>.pdf`, `.synctex.gz`, `.log`) via `publish` (F11).
- TeX runs use `cwd = layout.shadow_dir` and `-output-directory` inside the build directory.
- Files are read and written as bytes or with `surrogateescape`; line endings are preserved.
- Paths passed to TeX go through `tex_path` (forward slashes).
- External programs go through `proc.run`; TeX command lines only through `texdist`.
