"""The ``-recorder`` file (``.fls``) of a TeX run: files it read (design §6.5, C4).

Source files read through the shadow tree are tracked by digest, distribution files by a cheap
stat signature (an update means a new format and a cold build).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from chapmk.files import read_raw


def fls_inputs(fls: Path) -> list[str]:
    """The ``INPUT`` names of a recorder file, as written (relative or absolute); none if the
    file is missing."""
    if not fls.is_file():
        return []
    return [
        line[6:].rstrip("\r") for line in read_raw(fls).split("\n") if line.startswith("INPUT ")
    ]


def loaded_names(fls: Path) -> frozenset[str]:
    """File names (without directory) a run read, e.g. ``hyperref.sty``."""
    return frozenset(Path(name).name for name in fls_inputs(fls))


def _absolute(name: str, cwd: Path) -> Path:
    p = Path(name)
    return Path(os.path.normpath(p if p.is_absolute() else Path(cwd).absolute() / p))


def read_inputs(fls: Path, cwd: Path, within: Path) -> set[Path]:
    """Files read by a run that lie in ``within``, as paths below ``within``. The test is made
    on the normalised path before resolving symlinks (files of the shadow tree are symlinks
    into the source directory), and on the resolved path (a ``within`` given through a
    symlink)."""
    root = Path(within).absolute()
    resolved_root = root.resolve()
    found: set[Path] = set()
    for name in fls_inputs(fls):
        p = _absolute(name, cwd)
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
    """Files read by a run outside the ``internal`` directories (shadow tree, build and source
    directory, :attr:`chapmk.layout.Layout.internal_dirs`): the TeX distribution,
    ``TEXMFHOME``, ``TEXINPUTS``. Absolute, normalised paths of existing files."""
    roots = [Path(d).absolute() for d in internal]
    roots += [r.resolve() for r in roots]
    found: set[Path] = set()
    for name in fls_inputs(fls):
        p = _absolute(name, cwd)
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


def dist_signatures(fls: Path, cwd: Path, internal: Iterable[Path]) -> dict[str, str]:
    """:func:`stat_signatures` of the :func:`external_inputs` of a run."""
    return stat_signatures(external_inputs(fls, cwd, internal))
