"""Shadow tree of the source directory (PLAN §6.5, S2).

TeX runs work in ``<build>/src``, a mirror of the source tree made of symlinks (directories
are real). Build outputs of manual builds (``<jobname>.*`` except the main file, unit aux
files) are left out, so they can never be read by a run (F11).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from chapmk.analysis import Analysis

ALWAYS_SKIPPED_DIRS = frozenset({".git", ".hg", ".svn"})

#: Suffixes of files that LaTeX tools write for a job ``<jobname><suffix>``. Only these are
#: left out: other ``<jobname>.*`` files may be sources (e.g. ``pgfmanual.cfg``).
BUILD_OUTPUT_SUFFIXES = frozenset(
    {
        ".aux",
        ".toc",
        ".lof",
        ".lot",
        ".loalg",
        ".lol",
        ".tdo",
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


def build_output_filter(analysis: Analysis) -> Callable[[PurePosixPath], bool]:
    """Predicate for files to leave out: build outputs ``<jobname><suffix>`` in the top
    directory (:data:`BUILD_OUTPUT_SUFFIXES`) and the aux files of all includes."""
    outputs = {f"{analysis.jobname}{suffix}" for suffix in BUILD_OUTPUT_SUFFIXES}
    unit_aux = {inc.aux_name for inc in analysis.includes}

    def excluded(rel: PurePosixPath) -> bool:
        if len(rel.parts) == 1 and rel.name in outputs:
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
        return dst.readlink() == src
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


def sync_project_shadow(analysis: Analysis, shadow_dir: Path, build_dir: Path) -> ShadowStats:
    """:func:`sync_shadow` for an analysed project; the build directory is skipped."""
    return sync_shadow(
        analysis.source_dir,
        shadow_dir,
        skip_dirs=[build_dir],
        excluded=build_output_filter(analysis),
    )
