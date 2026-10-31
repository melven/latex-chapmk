# src/fastinc: module map for agents

Read this before adding code. Reuse the listed functions instead of writing new ones.
**Keep this file in sync**: every new or removed module or public function and every changed
responsibility is updated here in the same commit.

## Layering (imports only go downwards)

```
cli                       command line, exit codes
incremental               builder: full / cold / incremental / noop, verification, merge + publish
merge_pdf, state          PDF merge, canonical state (state.json)
fullbuild                 full-mode build; converge() fixpoint loop shared with cold builds
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
| `analysis.py` | §6.1: `\begin{document}`, inlined preamble inputs, format split point, includes, compilation units (A5), fingerprints, fallback reasons | `analyse(config) -> Analysis`; `Analysis` (`lines`, `begin_line`, `split_line`, `split_reason`, `includes`, `units`, `fingerprints`, `fallback_reasons`, `warnings`, `jobname`, `newline`), `Include`, `CompilationUnit`, `Fingerprints`, `read_source`/`encode_source` (exact byte round trip), `DENY_SPLIT`, `UNIT_HEADINGS`, `UNSUPPORTED_PACKAGES` |
| `gensrc.py` | §6.2: generated sources that keep line numbers | `format_source(a)`, `run_main(a, selection, deny_names)` (`None` = all units, `[]` = glue only; `deny_names` = extra run-local registers for fastinc.sty), `full_mode_input(a)`, `write_if_changed(path, text)`, `INI_PACKAGE`, `RUNTIME_PACKAGE` |
| `proc.py` | Run programs: argv only, stdin closed, combined output | `run(argv, cwd=, env=, timeout=, log_path=) -> ProcResult` (`ok`, `output`, `seconds`) |
| `texdist.py` | §6.16 distribution adapter. **Only place with engine flags.** | `detect() -> TexDistribution`, `TeXLive` (`pdflatex`, `format_build`, `biber`, `makeindex`, `environment`, `version`, `check_tools`), `deterministic_env(epoch)` (N4), `tex_path`, `TEX_DIR` |
| `layout.py` | Build directory parts and published outputs | `Layout` (`shadow_dir`, `fmt_dir`, `full_dir`, `runs_dir`, `canon_dir`, `output(suffix)`, `path_map()`), `make_layout(config, analysis)` |
| `shadow.py` | §6.5/S2 shadow tree (symlinks, build outputs excluded, refresh) | `sync_project_shadow(a, shadow_dir, build_dir)`, `sync_shadow(...)`, `build_output_filter(a)`, `ShadowStats` |
| `fmt.py` | §6.3 format build, reused while the stamp matches | `ensure_format(a, layout, dist, env) -> FormatInfo`, `format_stamp(a, version)` |
| `logs.py` | §6.13 log helpers | `map_paths(text, mapping)`, `first_error(log)` |
| `synctex.py` | §6.12/S10 SyncTeX files: read, write with recomputed `!` offsets, path mapping (keeps `/./`), merge of several runs | `read_lines`, `write_lines`, `serialise`, `map_input_paths`, `rewrite_paths`, `parse(path) -> ParsedSyncTex`, `merge(pages, map_path, out)`, `SyncTexError` |
| `publish.py` | Atomic output replacement with Windows retry and `.fastinc` fallback name | `publish(write, target) -> Path`, `copy_bytes(src)`, `text_writer(text)` |
| `runner.py` | §6.5 run directories and the parallel pool (threads waiting on subprocesses) | `RunSpec(name, selection)`, `RunResult`, `prepare_run_dir(a, layout, spec, canon_dir=, deny_names=)`, `run_one(...)`, `run_batch(a, layout, dist, env, specs, fmt_name, jobs)`, `RUN_MAIN` (fixed run-main name, found via `TEXINPUTS`), `DERIVED_SUFFIXES` |
| `records.py` | Parse fastinc.sty records (Appendix B) from a run directory | `read_run_records(run_dir, a) -> RunRecords` (`base`, `entries`, `glue_exits`, `absolute`, `units`, `checkpoints`, `bookmark_levels`, `pages`, `files`, `nomenclature`, `segments_in_order()`, `entry_state(seg)`), `read_nomenclature(nlo)`, `PageRecord`, `parse_vector`, `parse_indices`, `RecordError` |
| `fullbuild.py` | §6.14 full mode and the fixpoint loop | `full_build(a, layout, dist, env, report=) -> FullBuildResult`, `converge(job, outdir, cwd, dist, env, run_pass, ...)` (rerun while a build file read by a pass changed; biber/makeindex via `run_tools`), `PassResult`, `ToolState`, `read_inputs(fls, cwd, within)` |
| `aux.py` | §6.7 aux helpers (no Python list-file linker: TeX writes .toc etc. itself) | `segment_slices(main_aux_lines)` (per-segment main-aux lines, S5/S8), `content_lines` (drop `\relax`/`\providecommand`), `parse_bookmark(line) -> Bookmark`, `bookmark_levels(lines)`, `tex_octal_bytes`, `read_lines` |
| `state.py` | §6.6 canonical state `<build>/canon/state.json` | `State` (`epoch`, `fingerprints`, `format_stamp`, `includes`, `segments: {seg: SegmentArtifact(run, pages)}`, `segment_files`, `global_files`, `next_run`, `run_names()`, `new_run_name()`), `load_state`, `save_state` |
| `merge_pdf.py` | §6.11/S9 merge: pages, named destinations (first wins, dummies dropped, names undefined everywhere get pdfTeX's dummy), outline from bookmark records, page labels, catalog | `merge_pdf(pages, outline, catalog_from, out)`, `PageSource`, `OutlineEntry`, `page_labels`, `label_style`, `dummy_destinations(log)`, `MergeError` |
| `incremental.py` | Builder (M3): full mode for fallback reasons; cold build (all units with format + fastinc.sty to the fixpoint, commit); incremental step (dirty compilation units in one run, strict verification against canon, else cold build); merge + publish; run GC | `build(ctx, epoch, full=) -> BuildReport`, `Context`, `BuildReport` (`mode`, `reason`, `runs`, `compiled`, `to_json()`), `cold_build`, `incremental_step`, `publish_state`, `load_epoch`, `FallbackError` (`persistent`) |
| `check.py` | §3.3 comparison of two builds | `compare_pdfs(ref, got) -> Report`, `compare_synctex(ref, got, sources, cwd)`, `Report` (`ok`, `differences`, `counts`, `summary()`) |
| `cli.py` | `fastinc build [--full] [--check] [--report FILE]`, `fastinc check`, `fastinc clean` (only directories with `BUILD_DIR_MARKER`) | `main(argv, cwd) -> int` |
| `tex/` | LaTeX packages, see `tex/CLAUDE.md` | |

## Invariants

- Never write into the source directory except the published outputs (`<jobname>.pdf`, `.synctex.gz`, `.log`) via `publish` (F11).
- TeX runs use `cwd = layout.shadow_dir` and `-output-directory` inside the build directory.
- Files are read and written as bytes or with `surrogateescape`; line endings are preserved.
- Paths passed to TeX go through `tex_path` (forward slashes).
- External programs go through `proc.run`; TeX command lines only through `texdist`.
