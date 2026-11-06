"""Shared fixtures. Tests marked ``slow`` need TeX Live on PATH (dev container)."""

import functools
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from hypothesis import settings

# property tests: no deadline (timings vary under xdist), no example database (it would be a
# shared directory in the working tree)
settings.register_profile("chapmk", deadline=None, database=None)
settings.load_profile("chapmk")

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "tests" / "corpus"

# --- reference cache ----------------------------------------------------------------------------
# References (the --full build of `--check`, latexmk in the acceptance tests) are kept in
# REFERENCE_CACHE and reused in later test runs on this machine. Keyed by a hash of the source
# files, the TeX installation (tex_key) and, for --full references, the full-mode code
# (FULL_MODE_CODE). Entries of older keys stay unused: rm -rf .test-cache frees the space. CI
# restores the cache of an earlier run with the same image and full-mode code
# (.github/workflows/ci.yml and miktex-linux.yml; keep their keys and FULL_MODE_CODE in sync).
REFERENCE_CACHE = REPO / ".test-cache"
FULL_MODE_CODE = tuple(
    REPO / "src" / "chapmk" / name
    for name in (
        "fullbuild.py",
        "gensrc.py",
        "texdist.py",
        "pictures.py",
        "synctex.py",
        "publish.py",
        "tex/chapmk-ini.sty",
    )
)
_SRC_PLACEHOLDER = "/@chapmk-test-source@"
# files with a sibling .tex of the same stem are build outputs (fig/*.pdf, main.pdf, ...)
_OUTPUT_SUFFIXES = (".pdf", ".log", ".aux", ".synctex.gz")


def pytest_report_header(config: pytest.Config) -> list[str]:
    n = len(list(REFERENCE_CACHE.iterdir())) if REFERENCE_CACHE.is_dir() else 0
    return [
        f"reference cache: {REFERENCE_CACHE} ({n} entries, keyed by sources, TeX installation "
        "and full-mode code; rm -rf .test-cache frees the space)"
    ]


def _stdout(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, check=False).stdout


def _file_name_databases() -> list[Path]:
    """The file name databases, rewritten by every package installation or update. TeX Live:
    ``ls-R`` of the distribution trees. MiKTeX has no ``ls-R``: its ``*.fndb-5`` files in the
    data directories that ``initexmf --report`` names (``UserData``, ``CommonData``)."""
    trees = _stdout(["kpsewhich", "-var-value", "TEXMFDIST", "-var-value", "TEXMFLOCAL"]).split()
    dbs = [Path(tree) / "ls-R" for tree in trees]
    if shutil.which("initexmf"):
        for line in _stdout(["initexmf", "--report"]).splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() in ("UserData", "CommonData") and value.strip():
                dbs += sorted((Path(value.strip()) / "miktex" / "data" / "le").glob("*.fndb-5"))
    return [db for db in dbs if db.is_file()]


@functools.cache
def tex_key() -> str:
    """The TeX installation: pdflatex's version line and the stat signatures of the file name
    databases (:func:`_file_name_databases`)."""
    try:
        version = _stdout(["pdflatex", "--version"]).partition("\n")[0]
        dbs = _file_name_databases()
    except OSError:  # no TeX: nothing to build references with
        return "no-tex"
    parts = [version]
    for db in dbs:
        st = db.stat()
        parts.append(f"{db}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]


@functools.cache
def full_mode_key() -> str:
    """Hash of the code the --full output depends on (FULL_MODE_CODE)."""
    h = hashlib.sha256()
    for path in FULL_MODE_CODE:
        h.update(path.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def source_hash(src: Path, *extra: str) -> str:
    """Hash of the source files below ``src`` (hidden directories and build outputs excluded)."""
    h = hashlib.sha256("\0".join(extra).encode())
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if any(part.startswith(".") for part in rel.parts) or not path.is_file():
            continue
        suffix = next((s for s in _OUTPUT_SUFFIXES if path.name.endswith(s)), None)
        if suffix and (path.parent / (path.name[: -len(suffix)] + ".tex")).is_file():
            continue
        h.update(rel.as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()[:32]


def reuse_reference(
    key: str, src: Path, outputs: dict[str, Path], build: Callable[[], Any]
) -> None:
    """Copy the cached reference files ``outputs`` (name -> target) for ``key`` into place, or
    ``build()`` them and store them. SyncTeX files are stored with ``src`` replaced."""
    from chapmk.synctex import rewrite_paths

    key = f"{tex_key()}-{key}"
    entry = REFERENCE_CACHE / key
    if all((entry / name).is_file() for name in outputs):
        for name, target in outputs.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            if name.endswith(".synctex.gz"):
                rewrite_paths(entry / name, target, [(_SRC_PLACEHOLDER, str(src))])
            else:
                shutil.copyfile(entry / name, target)
        return
    build()
    tmp = REFERENCE_CACHE / f".{key}.{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, source in outputs.items():
        if not source.is_file():
            shutil.rmtree(tmp)
            return
        if name.endswith(".synctex.gz"):
            rewrite_paths(source, tmp / name, [(str(src), _SRC_PLACEHOLDER)])
        else:
            shutil.copyfile(source, tmp / name)
    try:
        tmp.rename(entry)
    except OSError:  # stored meanwhile by another worker
        shutil.rmtree(tmp, ignore_errors=True)


def _texinputs_hashes(env: Any) -> list[str]:
    """Hashes of the test's own TEXINPUTS directories (packages outside the source directory,
    standing in for distribution files): a reference depends on them too."""
    from chapmk.texdist import TEX_DIR

    out = []
    for entry in str(env.get("TEXINPUTS", "")).split(os.pathsep):
        d = Path(entry.rstrip("/"))
        if entry and d.is_dir() and d.resolve() != TEX_DIR:
            out.append(source_hash(d))
    return out


@pytest.fixture(scope="session", autouse=True)
def _cached_check_reference() -> Iterator[None]:
    """`--check` builds its --full reference through ``chapmk.cli.full_build``; reuse cached
    references. (`build --full` itself, the code under test in the acceptance tests, is not
    cached: it goes through ``chapmk.incremental``.)"""
    import chapmk.cli

    real = chapmk.cli.full_build

    def cached(analysis: Any, layout: Any, dist: Any, env: Any, **kwargs: Any) -> None:
        src = analysis.source_dir
        key = source_hash(
            src,
            "full",
            full_mode_key(),
            analysis.main.name,
            str(env.get("SOURCE_DATE_EPOCH")),
            str(kwargs.get("picture_cache")),
            *_texinputs_hashes(env),
        )
        outputs = {f"ref{s}": layout.output(s) for s in (".pdf", ".synctex.gz", ".log")}
        reuse_reference(key, src, outputs, lambda: real(analysis, layout, dist, env, **kwargs))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(chapmk.cli, "full_build", cached)
        yield


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("pdflatex"):
        return
    skip = pytest.mark.skip(reason="pdflatex not on PATH (run inside the dev container)")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def copy_corpus(tmp_path: Path) -> Iterator["CorpusCopier"]:
    yield CorpusCopier(tmp_path)


class CorpusCopier:
    """Copies a corpus directory to a temporary source directory (never build in the repo)."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path

    def __call__(self, name: str, dest: str = "src") -> Path:
        target = self.tmp_path / dest
        shutil.copytree(CORPUS / name, target, ignore=shutil.ignore_patterns("generate.py"))
        prepare_figures(target)
        return target


def prepare_figures(src: Path) -> None:
    """Compile ``fig/*.tex`` (standalone sources) to ``fig/*.pdf`` in a corpus copy."""
    for tex in sorted(src.glob("fig/*.tex")):
        subprocess.run(
            ["pdflatex", "-interaction=batchmode", "-halt-on-error", tex.name],
            cwd=tex.parent,
            env=dict(os.environ),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        for ext in (".aux", ".log"):
            tex.with_suffix(ext).unlink(missing_ok=True)


def hgb_class_loads_cmap() -> bool:
    """Whether the installed HagenbergThesis loads ``cmap`` in the format part of the hgb corpus:
    hgbthesis 2025/02/24 (MiKTeX 26.5) does, the current one (TeX Live 2026) does not. Such a
    format loses its immediate PDF objects (S13), so the hgb corpus builds in full mode there."""
    r = subprocess.run(["kpsewhich", "hgb.sty"], capture_output=True, text=True, check=False)
    path = r.stdout.strip()
    return bool(path) and "\\RequirePackage{cmap}" in Path(path).read_text(errors="replace")


#: SOURCE_DATE_EPOCH of all TeX tests (N4): without it a build uses the current time
EPOCH = "1700000000"


@pytest.fixture(autouse=True)
def fixed_epoch(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests marked ``slow`` (TeX runs) build with :data:`EPOCH`; a test may set another one
    (autouse: set before the test's other fixtures, e.g. a built corpus)."""
    if request.node.get_closest_marker("slow") is not None:
        monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)


@pytest.fixture(scope="session")
def thesis_template(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, Path]]:
    """(live source dir, cache dir): the thesis corpus after a cold build with --check,
    built once per session. Restored copies live at the same absolute path: the shadow tree
    (symlinks), run directories and SyncTeX files contain absolute paths."""
    from chapmk.cli import main

    base = tmp_path_factory.mktemp("thesis")
    live, cache = base / "live" / "src", base / "cache"
    shutil.copytree(CORPUS / "thesis", live, ignore=shutil.ignore_patterns("generate.py"))
    prepare_figures(live)
    report = base / "live" / "report.json"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SOURCE_DATE_EPOCH", EPOCH)
        rc = main(["build", "main.tex", "--check", "--report", str(report)], cwd=live)
    rep = json.loads(report.read_text())
    assert rc == 0, rep
    assert rep["mode"] == "cold" and rep["reason"] == "no previous state"
    shutil.copytree(live, cache, symlinks=True)
    yield live, cache


@pytest.fixture
def thesis(thesis_template: tuple[Path, Path]) -> Path:
    """A freshly restored, built thesis corpus (same absolute path in every test; built with
    :data:`EPOCH`, as :func:`fixed_epoch` sets for the test)."""
    live, cache = thesis_template
    shutil.rmtree(live)
    shutil.copytree(cache, live, symlinks=True)
    return live
