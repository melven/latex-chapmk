# CLAUDE.md

`fastinc`: an incremental, parallel pdfLaTeX build driver (Python) plus two small LaTeX packages.
**`PLAN.md` is the specification. Read it completely before any work.**

## Workflow

1. Milestones are worked in order: M0 (spikes) → M1 … M7 (`PLAN.md` §9). Do not start features before M0 is done.
2. Each spike S# gets:
   - a minimal reproducer in `tests/corpus/minimal/S#-*/`,
   - a note in `docs/spikes/S#.md` (question, setup, result, consequence for the plan).
3. If a spike contradicts `PLAN.md`, update `PLAN.md` in a separate commit (`plan: ...`). Never silently deviate from the plan.
4. **Decision points: stop and ask the user** with a short summary and options when:
   - S2 shows that the shadow tree (`PLAN.md` §6.5) breaks file resolution or SyncTeX paths,
   - S5 shows that `.bcf` patching is needed or not feasible,
   - S7 shows that running heads differ between partial and full runs,
   - any change would weaken the acceptance criterion (`PLAN.md` §3.3),
   - any non-goal (`PLAN.md` §1) seems necessary.
5. A milestone is done only when its "done when" condition holds and all tests pass.
6. Commits are small, one logical step each, with messages prefixed by the component: `driver:`, `tex:`, `merge:`, `test:`, `spike:`, `plan:`, `ci:`.

## Environment

Run everything inside the dev container (TeX Live full, Python venv, poppler, synctex):

```
docker build -t fastinc-dev .
docker run --rm -it -v "$PWD":/work -w /work fastinc-dev bash
```

or open the repository as a devcontainer (`.devcontainer/devcontainer.json`).

Behind a proxy: pass it as build args (`--build-arg HTTPS_PROXY=...`, `--network host` for a local proxy); if it intercepts TLS, add `--secret id=ca,src=<CA bundle incl. public CAs>`.

**Private benchmark document:** the environment variable `FASTINC_BENCH_DOC` points to the user's real main `.tex` file (mounted read-only). Use it only for `fastinc check` and benchmarks. Never commit or copy its content, file names or output into the repository. Report numbers only.

## Rules

**User sources and the build:**
- Never modify user sources. All generated files go into the build directory (`.fastinc/`).
- All TeX runs use the deterministic environment (`PLAN.md` N4) and go through `texdist.py` (no hard-coded engine flags elsewhere).

**Correctness:**
- Correctness first. Every optimisation needs a verification step or a fallback to a full build (`PLAN.md` §6.14).
- Do not weaken, skip or `xfail` acceptance or scenario tests to make them pass. If a test is wrong, explain why in the commit message.

**LaTeX packages** (`src/fastinc/tex/`):
- LaTeX2e plus kernel hooks; expl3 is allowed where it simplifies.
- Internal prefix `\fastinc@`.
- Records and hooks only, no logic. Keep the version string in sync with the driver.

**Python:**
- ≥ 3.10, type hints everywhere, `ruff` (lint and format), `mypy --strict` for `src/`.
- `pathlib` internally; forward slashes when passing paths to TeX.
- Use `subprocess` for external tools (no shell strings, no `fork`).
- Tests do not use the network.

## Tests

```
pytest -m "not slow"     # unit tests, fast
pytest                   # incl. TeX runs, scenarios (slow)
pytest -m acceptance     # scenario tests with the PLAN.md §3.3 comparison
```

- Markers: `slow` (runs TeX), `acceptance` (compares against `--full`), `bench` (manual only).
- Scenario tests (`PLAN.md` §8.2) assert both §3.3 equality and the expected set of compiled units, from `fastinc build --report json`.
- Windows/macOS/MiKTeX are tested only in CI (`.github/workflows/ci.yml`, extended in M7).
