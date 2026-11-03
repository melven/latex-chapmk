"""Format build (PLAN §6.3): dump the static preamble with mylatexformat, reuse while valid."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from chapmk.analysis import Analysis
from chapmk.errors import TexError
from chapmk.gensrc import format_source, write_if_changed
from chapmk.layout import Layout
from chapmk.logs import first_error, map_paths
from chapmk.proc import run
from chapmk.texdist import TEX_DIR, TexDistribution

FORMAT_NAME = "pre"
STAMP_FILE = "stamp.json"


@dataclass(frozen=True)
class FormatInfo:
    """A usable format: directory (for ``TEXFORMATS``), name (for ``-fmt``), whether rebuilt."""

    directory: Path
    name: str
    rebuilt: bool


def format_stamp(analysis: Analysis, dist_version: str) -> str:
    """Everything the format and the canonical state depend on (§6.3.1): the ``pre``
    fingerprint (lines and inlined inputs), the split line, the distribution version,
    chapmk-ini.sty and chapmk.sty."""
    ini = (TEX_DIR / "chapmk-ini.sty").read_bytes()
    runtime = (TEX_DIR / "chapmk.sty").read_bytes()
    data = {
        "pre": analysis.fingerprints.pre,
        "split_line": analysis.split_line,
        "dist": dist_version,
        "ini": hashlib.sha256(ini).hexdigest(),
        # not in the format, but its records are the canonical state's: a change means cold
        "runtime": hashlib.sha256(runtime).hexdigest(),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def ensure_format(
    analysis: Analysis, layout: Layout, dist: TexDistribution, env: Mapping[str, str]
) -> FormatInfo:
    """Return a valid format, rebuilding it if its stamp changed.

    The build runs with cwd = shadow tree, so relative ``\\input`` paths resolve. On failure a
    :class:`TexError` with the first (path-mapped) error is raised; the old format is removed.
    """
    fmt_dir = layout.fmt_dir
    fmt_file = fmt_dir / f"{FORMAT_NAME}.fmt"
    stamp_file = fmt_dir / STAMP_FILE
    stamp = format_stamp(analysis, dist.version)
    if fmt_file.is_file() and stamp_file.is_file() and stamp_file.read_text() == stamp:
        return FormatInfo(fmt_dir, FORMAT_NAME, rebuilt=False)

    fmt_dir.mkdir(parents=True, exist_ok=True)
    stamp_file.unlink(missing_ok=True)
    fmt_file.unlink(missing_ok=True)
    source = fmt_dir / f"{FORMAT_NAME}.tex"
    write_if_changed(source, format_source(analysis))
    result = run(
        dist.format_build(source, FORMAT_NAME, fmt_dir),
        cwd=layout.shadow_dir,
        env=env,
        log_path=fmt_dir / "build.out",
    )
    log_file = fmt_dir / f"{FORMAT_NAME}.log"
    if not result.ok or not fmt_file.is_file():
        log = log_file.read_text(errors="replace") if log_file.is_file() else result.output
        err = first_error(map_paths(log, layout.path_map()))
        raise TexError("format build failed", log=log_file, first_error=err)
    m = re.search(r"chapmk-pdf-objects:(\d+),(\d+),(\d+)", log_file.read_text(errors="replace"))
    if m and (int(m.group(2)) or int(m.group(3))):  # objects are dumped fine, xforms/images not
        fmt_file.unlink(missing_ok=True)
        raise TexError(
            "format build failed",
            log=log_file,
            first_error=(
                f"the preamble before line {analysis.split_line} creates PDF form xobjects or "
                f"images ({m.group(2)}/{m.group(3)}), which a format cannot hold; "
                "move that code after the split point (chapmk.toml: split.before)"
            ),
        )
    stamp_file.write_text(stamp)
    return FormatInfo(fmt_dir, FORMAT_NAME, rebuilt=True)
