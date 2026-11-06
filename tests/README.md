# Tests

Commands and rules: [CONTRIBUTING.md](../CONTRIBUTING.md#checks).

| Directory | Content | Marker |
|---|---|---|
| `unit/` | pure Python, no TeX | none |
| `slow/` | real TeX runs of single components | `slow` |
| `scenarios/` | edit scenarios ([design §8.2](../docs/design.md#82-scenario-tests)): build, edit, build; each build checked with `--check` | `slow`, `acceptance` |
| `acceptance/` | `--full` compared with latexmk ([design §3.3](../docs/design.md#33-acceptance-criterion-identical-output)) | `slow`, `acceptance` |
| `bench/` | benchmarks, manual only | `bench` |
| `corpus/` | test documents; never built in place (copy them with `copy_corpus`) | |

## Fixtures (`conftest.py`)

| Fixture | Scope | What it does |
|---|---|---|
| `copy_corpus` | function | `copy_corpus(name, dest="src")` copies `corpus/<name>` to `tmp_path/<dest>` (without `generate.py`) and compiles its `fig/*.tex` to PDF; returns the copy. |
| `thesis_template` | session (per xdist worker) | `(live, cache)`: the thesis corpus after a cold `build --check`, and a copy of it with the build directory. Built with `SOURCE_DATE_EPOCH` = `EPOCH` (`pytest.MonkeyPatch.context()`). |
| `thesis` | function | Restores `live` from `cache` (same absolute path: the shadow tree and SyncTeX files hold absolute paths); returns `live`. Tests on it must not depend on another test's edits. |
| `fixed_epoch` | function, autouse | Tests marked `slow` get `SOURCE_DATE_EPOCH` = `EPOCH` (a build without it uses the current time); a test may set another value. |
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

- `scenarios/_helpers.py`: `build(src, *args)` (exit code and JSON report), `checked(src,
  capsys, *args)` (`--check`: asserts success and PASS), `edit(path, old, new)` (asserts that
  `old` occurs; use it for every edit), report queries `selections`, `batches`,
  `reasons(report, unit=None)`, `mispredictions`, `run_with(report, arg)`; thesis corpus:
  `THESIS_UNITS`, `chapter(thesis, name)`, `lengthen(thesis, name)` (`LONG_TEXT`).
- `conftest.py`: `EPOCH` (the `SOURCE_DATE_EPOCH` of all TeX tests).
