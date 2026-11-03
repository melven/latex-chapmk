"""Locations of the build directory, its parts and the published outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chapmk.analysis import Analysis
from chapmk.config import Config
from chapmk.errors import ConfigError

DEFAULT_BUILD_DIR = ".chapmk"


@dataclass(frozen=True)
class Layout:
    """Directory structure of one project (PLAN §5, §6.5, §6.6).

    ``build_dir`` contains ``src`` (shadow tree), ``fmt`` (format), ``full`` (full-mode runs),
    ``runs`` (incremental runs), ``canon`` (canonical state) and the picture caches ``fig``
    (incremental) and ``fig-full`` (full mode; keys differ: §6.17). Outputs for the user go to
    ``out_dir`` (default: the source directory).
    """

    source_dir: Path
    build_dir: Path
    out_dir: Path
    jobname: str

    @property
    def shadow_dir(self) -> Path:
        return self.build_dir / "src"

    @property
    def fmt_dir(self) -> Path:
        return self.build_dir / "fmt"

    @property
    def full_dir(self) -> Path:
        return self.build_dir / "full"

    @property
    def runs_dir(self) -> Path:
        return self.build_dir / "runs"

    @property
    def canon_dir(self) -> Path:
        return self.build_dir / "canon"

    @property
    def fig_dir(self) -> Path:
        return self.build_dir / "fig"

    @property
    def full_fig_dir(self) -> Path:
        return self.build_dir / "fig-full"

    def output(self, suffix: str) -> Path:
        """Published file ``<out_dir>/<jobname><suffix>`` (``.pdf``, ``.synctex.gz``, ``.log``)."""
        return self.out_dir / f"{self.jobname}{suffix}"

    def path_map(self) -> list[tuple[str, str]]:
        """Prefix substitutions from build paths to user paths (logs, SyncTeX): the shadow
        tree maps to the source directory (S2, S10)."""
        return [(str(self.shadow_dir), str(self.source_dir))]


def build_dir_of(config: Config) -> Path:
    """The build directory: ``build_dir`` of the configuration, else per job,
    ``<source>/.chapmk/<jobname>`` (several main files in one directory keep their own
    format, state and caches). Needs no analysis, so ``clean`` works for a document that
    cannot be analysed (E7)."""
    if config.build_dir is not None:
        return config.build_dir
    if config.main is None:
        raise ConfigError("no main file (give MAIN or set 'main' in chapmk.toml)")
    return config.main.parent / DEFAULT_BUILD_DIR / config.main.stem


def make_layout(config: Config, analysis: Analysis) -> Layout:
    """Layout from the configuration (build/out directories) and the analysed main file."""
    build_dir = build_dir_of(config)
    out_dir = config.out_dir or analysis.source_dir
    return Layout(analysis.source_dir, build_dir, out_dir, analysis.jobname)
