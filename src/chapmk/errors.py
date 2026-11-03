"""Exception hierarchy. Every error shown to the user derives from :class:`ChapmkError`."""

from __future__ import annotations

from pathlib import Path


class ChapmkError(Exception):
    """Base class; ``str(err)`` is the message printed by the CLI."""

    exit_code = 2


class ConfigError(ChapmkError):
    """Invalid command line or ``chapmk.toml``."""


class AnalysisError(ChapmkError):
    """The document violates an assumption the driver cannot work around (PLAN §2)."""


class ToolError(ChapmkError):
    """An external tool is missing or failed outside a TeX run (biber, makeindex, ...)."""


class TexError(ChapmkError):
    """A TeX run failed. ``log`` is the run's log file, ``first_error`` its first error line."""

    exit_code = 1

    def __init__(self, message: str, log: Path | None = None, first_error: str | None = None):
        super().__init__(message)
        self.log = log
        self.first_error = first_error
