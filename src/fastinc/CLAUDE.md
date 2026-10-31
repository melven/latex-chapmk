# src/fastinc: module map for agents

Read this before adding code. Reuse the listed functions instead of writing new ones.
**Keep this file in sync**: every new or removed module or public function and every changed
responsibility is updated here in the same commit.

## Layering (imports only go downwards)

```
cli                       command line, exit codes
fullbuild                 full-mode build (fixpoint loop, publish)
fmt                       format build
check                     §3.3 comparison (pikepdf, poppler, synctex CLI)
shadow, layout, gensrc    shadow tree, directory layout, generated TeX sources
analysis                  static analysis of the sources
texdist, proc             TeX distribution adapter, subprocess helper
synctex, publish, logs    file formats and output handling
texsource, config, errors basics
```

## Modules

| Module | Purpose (PLAN §) | Public API |
|---|---|---|
| `errors.py` | Exceptions; `str(err)` is the user message; `exit_code` 2 (1 for `TexError`) | `FastincError`, `ConfigError`, `AnalysisError`, `ToolError`, `TexError(msg, log, first_error)` |
| `config.py` | `fastinc.toml` plus CLI overrides (§6.15) | `Config` (frozen; `effective_jobs`), `load_config(main, cwd, **overrides)`, `parse_config_file(path)`, `find_config_file(dir)`, `CONFIG_NAME` |
| `texsource.py` | Scanning TeX source without TeX: comments, braces, control words, arguments | `split_lines` (at `\n` only; never use `str.splitlines`), `strip_comment(s)`, `control_sequences`, `find_macros(text, names) -> [Macro]`, `read_group`, `read_optional`, `skip_space`, `LineIndex`, `depth_at_line_starts`, `split_list` |
| `analysis.py` | §6.1: `\begin{document}`, inlined preamble inputs, format split point, includes, compilation units (A5), fingerprints, fallback reasons | `analyse(config) -> Analysis`; `Analysis` (`lines`, `begin_line`, `split_line`, `split_reason`, `includes`, `units`, `fingerprints`, `fallback_reasons`, `warnings`, `jobname`, `newline`), `Include`, `CompilationUnit`, `Fingerprints`, `read_source`/`encode_source` (exact byte round trip), `DENY_SPLIT`, `UNIT_HEADINGS`, `UNSUPPORTED_PACKAGES` |
| `gensrc.py` | §6.2: generated sources that keep line numbers | `format_source(a)`, `run_main(a, selection)` (`None` = all units, `[]` = glue only), `full_mode_input(a)`, `write_if_changed(path, text)`, `INI_PACKAGE`, `RUNTIME_PACKAGE` |
| `proc.py` | Run programs: argv only, stdin closed, combined output | `run(argv, cwd=, env=, timeout=, log_path=) -> ProcResult` (`ok`, `output`, `seconds`) |
| `texdist.py` | §6.16 distribution adapter. **Only place with engine flags.** | `detect() -> TexDistribution`, `TeXLive` (`pdflatex`, `format_build`, `biber`, `makeindex`, `environment`, `version`, `check_tools`), `deterministic_env(epoch)` (N4), `tex_path`, `TEX_DIR` |
| `layout.py` | Build directory parts and published outputs | `Layout` (`shadow_dir`, `fmt_dir`, `full_dir`, `runs_dir`, `canon_dir`, `output(suffix)`, `path_map()`), `make_layout(config, analysis)` |
| `shadow.py` | §6.5/S2 shadow tree (symlinks, build outputs excluded, refresh) | `sync_project_shadow(a, shadow_dir, build_dir)`, `sync_shadow(...)`, `build_output_filter(a)`, `ShadowStats` |
| `fmt.py` | §6.3 format build, reused while the stamp matches | `ensure_format(a, layout, dist, env) -> FormatInfo`, `format_stamp(a, version)` |
| `logs.py` | §6.13 log helpers | `map_paths(text, mapping)`, `first_error(log)` |
| `synctex.py` | §6.12/S10 SyncTeX files: read, write with recomputed `!` offsets, path mapping (keeps `/./`) | `read_lines`, `write_lines`, `serialise`, `map_input_paths`, `rewrite_paths` |
| `publish.py` | Atomic output replacement with Windows retry and `.fastinc` fallback name | `publish(write, target) -> Path`, `copy_bytes(src)` |
| `fullbuild.py` | §6.14 full mode: pdflatex, biber, makeindex until no file read by a pass changed during it; publish | `full_build(a, layout, dist, env, report=) -> FullBuildResult`, `read_inputs(fls, cwd, within)` |
| `check.py` | §3.3 comparison of two builds | `compare_pdfs(ref, got) -> Report`, `compare_synctex(ref, got, sources, cwd)`, `Report` (`ok`, `differences`, `counts`, `summary()`) |
| `cli.py` | `fastinc build` (M1: always full mode), `fastinc clean` (only directories with `BUILD_DIR_MARKER`) | `main(argv, cwd) -> int` |
| `tex/` | LaTeX packages, see `tex/CLAUDE.md` | |

## Invariants

- Never write into the source directory except the published outputs (`<jobname>.pdf`, `.synctex.gz`, `.log`) via `publish` (F11).
- TeX runs use `cwd = layout.shadow_dir` and `-output-directory` inside the build directory.
- Files are read and written as bytes or with `surrogateescape`; line endings are preserved.
- Paths passed to TeX go through `tex_path` (forward slashes).
- External programs go through `proc.run`; TeX command lines only through `texdist`.
