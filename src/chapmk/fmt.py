"""Format build (design §6.3): dump the static preamble with mylatexformat, reuse while valid."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import chapmk
from chapmk.analysis import Analysis
from chapmk.errors import TexError
from chapmk.files import changed_files, digest, read_log, write_atomic, write_if_changed
from chapmk.gensrc import format_source
from chapmk.layout import Layout
from chapmk.logs import run_error
from chapmk.proc import run
from chapmk.shadow import changed_signatures, external_inputs, source_inputs, stat_signatures
from chapmk.texdist import TEX_DIR, TexDistribution

FORMAT_NAME = "pre"
STAMP_FILE = "stamp.json"


@dataclass(frozen=True)
class FormatInfo:
    """A usable format: directory (for ``TEXFORMATS``), name, whether rebuilt."""

    directory: Path
    name: str
    rebuilt: bool

    @property
    def path(self) -> Path:
        """The format file (passed to :meth:`TexDistribution.pdflatex`)."""
        return self.directory / f"{self.name}.fmt"


def format_stamp(analysis: Analysis, dist_version: str) -> str:
    """Everything the format and the canonical state depend on (§6.3.1): the ``pre``
    fingerprint (lines and inlined inputs), the split line, the distribution version,
    chapmk-ini.sty, chapmk.sty and the driver version (record parsing, state semantics)."""
    ini = (TEX_DIR / "chapmk-ini.sty").read_bytes()
    runtime = (TEX_DIR / "chapmk.sty").read_bytes()
    data = {
        "pre": analysis.fingerprints.pre,
        "split_line": analysis.split_line,
        "dist": dist_version,
        "ini": hashlib.sha256(ini).hexdigest(),
        # not in the format, but its records are the canonical state's: a change means cold
        "runtime": hashlib.sha256(runtime).hexdigest(),
        "chapmk": chapmk.__version__,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _read_stamp(stamp_file: Path) -> tuple[str, dict[str, str], dict[str, str]]:
    """(stamp, source inputs, distribution inputs) of a format; empty if missing or
    unreadable."""
    try:
        data = json.loads(stamp_file.read_bytes())
        return (
            str(data["stamp"]),
            {str(k): str(v) for k, v in data["inputs"].items()},
            {str(k): str(v) for k, v in data["dist"].items()},
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "", {}, {}


def format_inputs(layout: Layout) -> dict[str, str]:
    """Source files read by the format build (local class, packages, ``.cfg`` files before the
    split point; relative to the source directory) with their digests at the build. They are
    global inputs of the canonical state: a change means a cold build and a new format."""
    return _read_stamp(layout.fmt_dir / STAMP_FILE)[1]


def format_dist_inputs(layout: Layout) -> dict[str, str]:
    """Distribution files read by the format build with their stat signatures
    (:func:`chapmk.shadow.stat_signatures`): an update (``tlmgr``) means a new format and a
    cold build, the pdfTeX banner changes only yearly (C4)."""
    return _read_stamp(layout.fmt_dir / STAMP_FILE)[2]


def internal_dirs(layout: Layout) -> tuple[Path, ...]:
    """Directories whose files are not distribution inputs (:func:`external_inputs`)."""
    return (layout.shadow_dir, layout.build_dir, layout.source_dir)


def _lost_state(log: str) -> str | None:
    """What the format part did that a dump loses (S13), from the probes of the format source
    and pdfTeX's warning; None if nothing. Reserved \\pdfobj objects are kept."""
    m = re.search(r"chapmk-pdf-objects:(\d+),(\d+),(\d+)", log)
    if m and (int(m.group(2)) or int(m.group(3))):
        return f"creates PDF form xobjects or images ({m.group(2)}/{m.group(3)})"
    if "dangling objects discarded" in log:
        return "writes PDF objects immediately (e.g. the cmap package's ToUnicode maps)"
    m = re.search(r"chapmk-pdf-colorstacks:(\d+)", log)
    if m and int(m.group(1)) > 1:
        return f"creates colour stacks ({int(m.group(1)) - 1}, \\pdfcolorstackinit)"
    m = re.search(r"chapmk-pdf-unrecorded:(\S+)", log)
    if m:
        return f"calls \\{m.group(1)} without a braced argument"
    return None


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
    old_stamp, inputs, dist_inputs = _read_stamp(stamp_file)
    if (
        fmt_file.is_file()
        and old_stamp == stamp
        and not changed_files(layout.source_dir, inputs)
        and not changed_signatures(dist_inputs)
    ):
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
        err = run_error(log_file, result.output, layout.path_map())
        raise TexError("format build failed", log=log_file, first_error=err)
    lost = _lost_state(read_log(log_file))
    if lost:
        fmt_file.unlink(missing_ok=True)
        raise TexError(
            "format build failed",
            log=log_file,
            first_error=(
                f"the preamble before line {analysis.split_line} {lost}, which a format cannot "
                "keep; move that code after the split point (chapmk.toml: format.split_before)"
            ),
        )
    fls = fmt_dir / f"{FORMAT_NAME}.fls"
    inputs = {
        name: digest(layout.source_dir / name)
        for name in sorted(source_inputs(fls, layout.shadow_dir, layout.source_dir))
    }
    dist_inputs = stat_signatures(external_inputs(fls, layout.shadow_dir, internal_dirs(layout)))
    write_atomic(
        stamp_file,
        json.dumps({"stamp": stamp, "inputs": inputs, "dist": dist_inputs}, sort_keys=True),
    )
    return FormatInfo(fmt_dir, FORMAT_NAME, rebuilt=True)
