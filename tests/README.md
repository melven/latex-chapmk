# Tests

Commands and rules: [CONTRIBUTING.md](../CONTRIBUTING.md#checks).

| Directory | Content | Marker |
|---|---|---|
| `unit/` | pure Python, no TeX | none |
| `slow/` | real TeX runs of single components | `slow` |
| `scenarios/` | edit scenarios (PLAN §8.2): build, edit, build; each build checked with `--check` | `slow` |
| `acceptance/` | `--full` compared with latexmk (PLAN §3.3) | `slow`, `acceptance` |
| `bench/` | benchmarks, manual only | `bench` |
| `corpus/` | test documents; never built in place (copy them with `copy_corpus`) | |

## Fixtures (`conftest.py`)

| Fixture | Scope | What it does |
|---|---|---|
| `copy_corpus` | function | `copy_corpus(name, dest="src")` copies `corpus/<name>` to `tmp_path/<dest>` (without `generate.py`) and compiles its `fig/*.tex` to PDF; returns the copy. |
| `thesis_template` | session (per xdist worker) | `(live, cache)`: the thesis corpus after a cold `build --check`, and a copy of it with the build directory. Sets `SOURCE_DATE_EPOCH` in `os.environ` during that build (a session fixture cannot use `monkeypatch`) and restores it. |
| `thesis` | function | Restores `live` from `cache` (same absolute path: the shadow tree and SyncTeX files hold absolute paths) and sets `SOURCE_DATE_EPOCH` with `monkeypatch`; returns `live`. Tests on it must not depend on another test's edits. |
| `_cached_check_reference` | session, autouse | Replaces `chapmk.cli.full_build` (the `--full` reference of `--check`) by a cached version. `build --full` itself is not cached. |

The slow tests are skipped when `pdflatex` is not on `PATH`.

## Reference cache

`--check` references and latexmk builds are stored in `.test-cache/` (`reuse_reference`),
keyed by `source_hash` of the source files, `tex_key()` (pdflatex version, `ls-R`
signatures) and, for `--full` references, `full_mode_key()` (`FULL_MODE_CODE`) plus the
test's `TEXINPUTS` directories, `SOURCE_DATE_EPOCH` and the picture-cache option. Entries
are written atomically (rename), so parallel workers can share the cache. Old entries stay
unused; `rm -rf .test-cache` frees the space.

## Helpers

- `scenarios/_helpers.py`: `build(src, *args)` (exit code and JSON report), `edit(path,
  old, new)` (asserts that `old` occurs), `selections(report)`, `EPOCH`.
