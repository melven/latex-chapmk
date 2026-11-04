"""Shadow tree of the source directory (design §6.5, S2).

TeX runs work in ``<build>/src``, a mirror of the source tree made of symlinks (directories
are real). Build outputs of manual builds (``<jobname>.*`` except the main file, unit aux
files) are left out, so they can never be read by a run (F11).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from chapmk.analysis import Analysis
from chapmk.facts import DEFAULT_LIST_SUFFIXES, TOOL_SUFFIXES
from chapmk.files import read_raw
from chapmk.layout import DEFAULT_BUILD_DIR

ALWAYS_SKIPPED_DIRS = frozenset({".git", ".hg", ".svn"})

#: Suffixes of files that LaTeX tools write for a job ``<jobname><suffix>``. Only these are
#: left out: other ``<jobname>.*`` files may be sources (e.g. ``pgfmanual.cfg``).
BUILD_OUTPUT_SUFFIXES = frozenset(
    {
        ".aux",
        *DEFAULT_LIST_SUFFIXES,
        *TOOL_SUFFIXES,
        ".out",
        ".log",
        ".fls",
        ".fdb_latexmk",
        ".synctex.gz",
        ".synctex(busy)",
        ".synctex",
        ".pdf",
        ".dvi",
        ".xdv",
        ".bbl",
        ".bcf",
        ".blg",
        ".run.xml",
        ".nlo",
        ".nls",
        ".ilg",
        ".idx",
        ".ind",
        ".glo",
        ".gls",
        ".glg",
        ".ist.bak",
        ".nav",
        ".snm",
        ".vrb",
        ".frec",
        ".auxlock",
        ".lock",
    }
)


@dataclass(frozen=True)
class ShadowStats:
    """Result of :func:`sync_shadow`: entries created, removed and present afterwards."""

    created: int
    removed: int
    total: int


def build_output_filter(
    analysis: Analysis, list_suffixes: Sequence[str] = ()
) -> Callable[[PurePosixPath], bool]:
    """Predicate for files to leave out: build outputs ``<jobname><suffix>`` in the top
    directory (:data:`BUILD_OUTPUT_SUFFIXES`) and the aux files of all includes."""
    outputs = {f"{analysis.jobname}{suffix}" for suffix in (*BUILD_OUTPUT_SUFFIXES, *list_suffixes)}
    unit_aux = {inc.aux_name for inc in analysis.includes}

    # list files of any list (.loa, .loe, tocbasic's \DeclareNewTOC ...): the extension of a
    # new kind is recorded only by the first run, which must not read a stale one already
    lists = re.compile(re.escape(analysis.jobname) + r"\.lo[a-z0-9]*")

    def excluded(rel: PurePosixPath) -> bool:
        if len(rel.parts) == 1 and (rel.name in outputs or lists.fullmatch(rel.name)):
            return True
        return rel.as_posix() in unit_aux

    return excluded


def _link(src: Path, dst: Path) -> None:
    """Symlink, else hardlink, else copy (Windows without symlink privilege)."""
    try:
        dst.symlink_to(src)
        return
    except OSError:
        pass
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _is_current(src: Path, dst: Path) -> bool:
    if dst.is_symlink():
        if sys.platform != "win32":
            return dst.readlink() == src
        # Windows: readlink may return another form of the path (``\\?\`` prefix, case)
        try:
            return dst.samefile(src)
        except OSError:  # broken link
            return False
    if not dst.is_file():
        return False
    try:
        return src.samefile(dst) or (
            dst.stat().st_mtime >= src.stat().st_mtime and dst.stat().st_size == src.stat().st_size
        )
    except OSError:
        return False


def sync_shadow(
    source_dir: Path,
    shadow_dir: Path,
    *,
    skip_dirs: Iterable[Path],
    excluded: Callable[[PurePosixPath], bool],
) -> ShadowStats:
    """Make ``shadow_dir`` mirror ``source_dir`` (idempotent; refresh once per build).

    ``skip_dirs`` (absolute, e.g. the build directory) and version-control directories are
    not mirrored. Entries that are no longer wanted are removed.
    """
    skip = {p.resolve() for p in skip_dirs} | {shadow_dir.resolve()}
    wanted_files: dict[PurePosixPath, Path] = {}
    wanted_dirs: set[PurePosixPath] = {PurePosixPath(".")}
    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in ALWAYS_SKIPPED_DIRS and (root_path / d).resolve() not in skip
        )
        rel_root = PurePosixPath(root_path.relative_to(source_dir).as_posix())
        for d in dirs:
            wanted_dirs.add(rel_root / d)
        for f in files:
            rel = rel_root / f
            if not excluded(rel):
                wanted_files[rel] = root_path / f

    created = removed = 0
    shadow_dir.mkdir(parents=True, exist_ok=True)
    # remove what is not wanted (bottom-up, so emptied directories can go)
    for root, dirs, files in os.walk(shadow_dir, topdown=False):
        root_path = Path(root)
        rel_root = PurePosixPath(root_path.relative_to(shadow_dir).as_posix())
        for name in files + [d for d in dirs if (root_path / d).is_symlink()]:
            rel = rel_root / name
            if rel not in wanted_files or not _is_current(wanted_files[rel], root_path / name):
                (root_path / name).unlink()
                removed += 1
        for d in dirs:
            rel = rel_root / d
            if rel not in wanted_dirs and not (root_path / d).is_symlink():
                shutil.rmtree(root_path / d)
                removed += 1
    for rel in sorted(wanted_dirs):
        (shadow_dir / rel).mkdir(parents=True, exist_ok=True)
    for rel, src in wanted_files.items():
        dst = shadow_dir / rel
        if not dst.is_symlink() and not dst.exists():
            _link(src, dst)
            created += 1
    return ShadowStats(created, removed, len(wanted_files))


def sync_project_shadow(
    analysis: Analysis, shadow_dir: Path, build_dir: Path, list_suffixes: Sequence[str] = ()
) -> ShadowStats:
    """:func:`sync_shadow` for an analysed project; the build directory and the default build
    root (the build directories of all jobs) are skipped."""
    return sync_shadow(
        analysis.source_dir,
        shadow_dir,
        skip_dirs=[build_dir, analysis.source_dir / DEFAULT_BUILD_DIR],
        excluded=build_output_filter(analysis, list_suffixes),
    )


def read_inputs(fls: Path, cwd: Path, within: Path) -> set[Path]:
    """Files read by a run (``INPUT`` lines of the ``-recorder`` file) that lie in ``within``,
    as paths below ``within``. The test is made on the normalised path before resolving
    symlinks (files of the shadow tree are symlinks into the source directory), and on the
    resolved path (a ``within`` given through a symlink)."""
    if not fls.is_file():
        return set()
    root = Path(within).absolute()
    resolved_root = root.resolve()
    found: set[Path] = set()
    for line in read_raw(fls).split("\n"):
        if line.startswith("INPUT "):
            p = Path(line[6:].rstrip("\r"))
            p = Path(os.path.normpath(p if p.is_absolute() else Path(cwd).absolute() / p))
            if p.is_relative_to(root):
                rel = p.relative_to(root)
            elif p.resolve().is_relative_to(resolved_root):
                rel = p.resolve().relative_to(resolved_root)
            else:
                continue
            if (root / rel).is_file():
                found.add(root / rel)
    return found


def source_inputs(fls: Path, shadow_dir: Path, source_dir: Path) -> set[str]:
    """Source files a run read through the shadow tree: the :func:`read_inputs` below
    ``shadow_dir`` that exist in ``source_dir``, as relative posix names."""
    root = Path(shadow_dir).absolute()
    return {
        name
        for path in read_inputs(fls, shadow_dir, shadow_dir)
        if (source_dir / (name := path.relative_to(root).as_posix())).is_file()
    }


def external_inputs(fls: Path, cwd: Path, internal: Iterable[Path]) -> set[Path]:
    """Files read by a run (``INPUT`` lines) outside the ``internal`` directories (shadow
    tree, build and source directory): the TeX distribution, ``TEXMFHOME``, ``TEXINPUTS``.
    Absolute, normalised paths of existing files."""
    if not fls.is_file():
        return set()
    roots = [Path(d).absolute() for d in internal]
    roots += [r.resolve() for r in roots]
    found: set[Path] = set()
    for line in read_raw(fls).split("\n"):
        if line.startswith("INPUT "):
            p = Path(line[6:].rstrip("\r"))
            p = Path(os.path.normpath(p if p.is_absolute() else Path(cwd).absolute() / p))
            if any(p.is_relative_to(r) for r in roots) or not p.is_file():
                continue
            if not any(p.resolve().is_relative_to(r) for r in roots):
                found.add(p)
    return found


def _stat(path: Path) -> str:
    try:
        st = path.stat()
    except OSError:
        return ""
    return f"{st.st_size}:{st.st_mtime_ns}"


def stat_signatures(paths: Iterable[Path]) -> dict[str, str]:
    """``{path: "size:mtime_ns"}``: cheap change detection for distribution files (C4)."""
    return {p.as_posix(): _stat(p) for p in paths}


def changed_signatures(signatures: Mapping[str, str]) -> list[str]:
    """Paths whose size or mtime changed since :func:`stat_signatures` (or that vanished)."""
    return [p for p, s in signatures.items() if _stat(Path(p)) != s]
