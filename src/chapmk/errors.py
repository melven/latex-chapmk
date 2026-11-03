"""Exception hierarchy. Every error shown to the user derives from :class:`ChapmkError`."""

from __future__ import annotations

from pathlib import Path


class ChapmkError(Exception):
    """Base class; ``str(err)`` is the message printed by the CLI."""

    exit_code = 2


class FallbackError(ChapmkError):
    """The incremental machinery cannot handle this build, full mode can (§6.14): unsupported
    construct, unreadable or inconsistent records, tool inputs, merge. Handled only by the
    builder (``incremental.build``), which falls back to full mode (D3). ``persistent``: the
    reason holds until the main file changes (the next builds skip the attempt)."""

    def __init__(self, message: str, persistent: bool = False):
        super().__init__(message)
        self.persistent = persistent


class SelfCheckError(FallbackError):
    """A runtime self-check found an inconsistency between chapmk's own result and what TeX
    wrote (C14): a bug or an unsupported construct. The build falls back to full mode."""

    def __init__(self, message: str):
        super().__init__(f"self-check failed: {message} (please report this)")


class InternalError(ChapmkError):
    """An unexpected exception (a bug): exit code 3."""

    exit_code = 3


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
