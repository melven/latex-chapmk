"""Configuration: ``fastinc.toml`` merged with command-line overrides (PLAN §6.15)."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from fastinc.errors import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

CONFIG_NAME = "fastinc.toml"


@dataclass(frozen=True)
class Config:
    """Effective configuration. Paths are absolute once :func:`load_config` returns."""

    main: Path | None = None
    jobs: int = 0
    build_dir: Path | None = None
    out_dir: Path | None = None
    split_before: tuple[str, ...] = ()
    lint_allow: tuple[str, ...] = ()
    aux_self: tuple[str, ...] = ()
    aux_ignore: tuple[str, ...] = ()
    state_ignore: tuple[str, ...] = ()
    unit_headings: tuple[str, ...] = ()
    keep_runs: bool = False
    verbose: bool = False
    config_file: Path | None = field(default=None, compare=False)

    @property
    def effective_jobs(self) -> int:
        """``jobs``, with 0 meaning the CPU count."""
        return self.jobs if self.jobs > 0 else (os.cpu_count() or 1)


# table.key -> (Config field, kind)
_SCHEMA: dict[str, tuple[str, str]] = {
    "main": ("main", "path"),
    "jobs": ("jobs", "int"),
    "build_dir": ("build_dir", "path"),
    "out_dir": ("out_dir", "path"),
    "format.split_before": ("split_before", "regexes"),
    "lint.allow": ("lint_allow", "strings"),
    "aux.self": ("aux_self", "regexes"),
    "aux.ignore": ("aux_ignore", "regexes"),
    "state.ignore": ("state_ignore", "strings"),
    "units.heading": ("unit_headings", "strings"),
}


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def _convert(key: str, kind: str, value: Any, base: Path) -> Any:
    if kind == "path":
        if not isinstance(value, str):
            raise ConfigError(f"{key}: expected a path string, got {value!r}")
        return (base / value).resolve()
    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ConfigError(f"{key}: expected a non-negative integer, got {value!r}")
        return value
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{key}: expected a list of strings, got {value!r}")
    if kind == "regexes":
        for v in value:
            try:
                re.compile(v)
            except re.error as err:
                raise ConfigError(f"{key}: invalid regular expression {v!r}: {err}") from err
    return tuple(value)


def parse_config_file(path: Path) -> Config:
    """Parse ``fastinc.toml``; relative paths are resolved against its directory."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise ConfigError(f"{path}: {err}") from err
    values: dict[str, Any] = {}
    for key, value in _flatten(data).items():
        if key not in _SCHEMA:
            raise ConfigError(f"{path}: unknown setting {key!r}")
        name, kind = _SCHEMA[key]
        values[name] = _convert(f"{path}: {key}", kind, value, path.parent)
    return Config(config_file=path, **values)


def find_config_file(start: Path) -> Path | None:
    """``fastinc.toml`` in ``start`` (a directory), if present."""
    candidate = start / CONFIG_NAME
    return candidate if candidate.is_file() else None


def load_config(
    main: Path | None,
    cwd: Path,
    *,
    jobs: int | None = None,
    build_dir: Path | None = None,
    out_dir: Path | None = None,
    keep_runs: bool = False,
    verbose: bool = False,
) -> Config:
    """Effective configuration for a command.

    The config file is looked up next to ``main`` if given, else in ``cwd``. Command-line
    values override file values. The main file must exist afterwards.
    """
    main_abs = (cwd / main).resolve() if main is not None else None
    cfg_file = find_config_file(main_abs.parent if main_abs else cwd)
    cfg = parse_config_file(cfg_file) if cfg_file else Config()
    overrides: dict[str, Any] = {"keep_runs": keep_runs or cfg.keep_runs, "verbose": verbose}
    if main_abs is not None:
        overrides["main"] = main_abs
    if jobs is not None:
        overrides["jobs"] = jobs
    if build_dir is not None:
        overrides["build_dir"] = (cwd / build_dir).resolve()
    if out_dir is not None:
        overrides["out_dir"] = (cwd / out_dir).resolve()
    cfg = replace(cfg, **overrides)
    if cfg.main is None:
        raise ConfigError(f"no main file given and no 'main' in {CONFIG_NAME}")
    if not cfg.main.is_file():
        raise ConfigError(f"main file not found: {cfg.main}")
    if cfg.main.suffix != ".tex":
        raise ConfigError(f"main file must have the extension .tex: {cfg.main}")
    return cfg
