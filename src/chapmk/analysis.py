"""Static project analysis (design §6.1): preamble, format split point, units, fingerprints.

Works on the source text only, no TeX runs. Results are deterministic for given sources and
configuration. Reasons that force full-build mode (§6.14) are collected, not raised.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from chapmk.config import Config
from chapmk.errors import AnalysisError
from chapmk.facts import SECTION_HEADINGS, UNIT_HEADINGS, UNSUPPORTED_PACKAGES
from chapmk.segment import document_order, glue_ids, seg_index, unit_ids
from chapmk.texsource import (
    LineIndex,
    depth_at_line_starts,
    find_macros,
    open_conditional_at_line_starts,
    skip_space,
    split_lines,
    split_list,
    strip_comments,
)

#: Preamble patterns that end the format part (design §6.3.2). Config adds ``format.split_before``.
DENY_SPLIT: tuple[str, ...] = (
    r"\\tikzexternalize\b",
    r"\\makeindex\b",
    r"\\makeglossaries\b",
    r"\\usepackage\s*(\[[^\]]*\])?\s*\{[^}]*\bminted\b",
    # code that creates PDF form xobjects or images at load time cannot be dumped into a
    # format (pgf manual: the fadings library runs \pdfxform); plain \pdfobj objects can
    r"(?<![\w@])fadings(?![\w@])",
    r"\\(tikzfading|pgfdeclarefading|pgfdeclareimage)(?![A-Za-z@])",
    r"\\pdf(xform|ximage)(?![A-Za-z@])",
)

_INPUT_MACROS = {"input", "include"}
_MAX_INPUT_DEPTH = 20


def read_source(path: Path) -> str:
    """Read a TeX source file as text; undecodable bytes round-trip (surrogateescape)."""
    try:
        return path.read_bytes().decode("utf-8", "surrogateescape")
    except OSError as err:
        raise AnalysisError(f"cannot read {path}: {err}") from err


def encode_source(text: str) -> bytes:
    """Inverse of :func:`read_source`."""
    return text.encode("utf-8", "surrogateescape")


@dataclass(frozen=True)
class Include:
    """An ``\\include`` in the main body: argument, source file, line in main file, headedness
    and the leading heading command (``chapter``, ``addchap*``, ...) of a headed include."""

    arg: str
    path: Path
    line: int
    headed: bool
    heading: str | None = None

    @property
    def resets(self) -> str | None:
        """The counter a numbered leading heading steps (its reset list then applies before
        any content of the include), else None."""
        return self.heading if self.heading in ("part", "chapter", "section") else None

    @property
    def name(self) -> str:
        """The unit's file name without ``.tex``, normalised: ``./ch/a`` and ``ch/a.tex`` are
        ``ch/a`` (LaTeX accepts both forms). ``arg`` stays as written: ``\\includeonly``
        must name the unit the same way."""
        return include_name(self.arg)

    @property
    def aux_name(self) -> str:
        """Name of the unit's aux file relative to the output directory (``ch/a.aux``)."""
        return f"{self.name}.aux"


def include_name(arg: str) -> str:
    """:attr:`Include.name` of an ``\\include`` argument or a recorded file name."""
    name = posixpath.normpath(arg)
    return name[: -len(".tex")] if name.endswith(".tex") else name


@dataclass(frozen=True)
class CompilationUnit:
    """Consecutive includes that are always compiled together (A5): a headed include plus the
    unheaded includes that follow it."""

    index: int
    includes: tuple[Include, ...]

    @property
    def name(self) -> str:
        return self.includes[0].arg


@dataclass(frozen=True)
class Fingerprints:
    """sha256 hex digests of the main-file parts (§6.1 step 4), including inlined inputs."""

    pre: str
    post: str
    body: str


@dataclass(frozen=True)
class Analysis:
    """Result of :func:`analyse`. Line numbers are 1-based lines of the main file."""

    main: Path
    source_dir: Path
    lines: tuple[str, ...]
    begin_line: int
    split_line: int
    split_reason: str
    preamble_inputs: tuple[Path, ...]
    includes: tuple[Include, ...]
    units: tuple[CompilationUnit, ...]
    fingerprints: Fingerprints
    fallback_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=(), compare=False)

    @property
    def jobname(self) -> str:
        return self.main.stem

    @property
    def segments(self) -> list[str]:
        """All segment ids in document order (:func:`chapmk.segment.document_order`)."""
        return document_order(len(self.includes))

    @property
    def unit_segments(self) -> list[str]:
        """``U1 ... Un``."""
        return unit_ids(len(self.includes))

    @property
    def glue_segments(self) -> list[str]:
        """``G0 ... Gn``."""
        return glue_ids(len(self.includes))

    def include_of(self, seg: str) -> Include:
        """The include of unit segment ``U<k>``."""
        return self.includes[seg_index(seg) - 1]

    @property
    def newline(self) -> str:
        """Line ending of the main file (``\\r\\n`` or ``\\n``)."""
        return "\r\n" if self.lines and self.lines[0].endswith("\r\n") else "\n"


def _sha256(parts: list[str]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(encode_source(part))
        h.update(b"\0")
    return h.hexdigest()


def _resolve_input(source_dir: Path, arg: str) -> Path | None:
    """File read by ``\\input{arg}`` if it lies in the source tree; ``None`` otherwise."""
    for candidate in (arg, f"{arg}.tex"):
        path = (source_dir / candidate).resolve()
        if path.is_file() and path.is_relative_to(source_dir):
            return path
    return None


@dataclass
class _InputScan:
    """Inlined preamble input: matching deny pattern (if any) and all files read."""

    deny_match: str | None = None
    files: list[Path] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)


def _scan_inputs(
    text: str, source_dir: Path, deny: list[re.Pattern[str]], depth: int, scan: _InputScan
) -> None:
    """Recursively inline ``\\input`` files of comment-free ``text``, checking deny patterns."""
    if depth > _MAX_INPUT_DEPTH:
        raise AnalysisError("\\input nesting too deep in the preamble (cycle?)")
    for macro in find_macros(text, _INPUT_MACROS):
        if macro.argument is None:
            continue
        path = _resolve_input(source_dir, macro.argument.strip())
        if path is None or path in scan.files:
            continue
        raw = read_source(path)
        scan.files.append(path)
        scan.texts.append(raw)
        body = strip_comments(raw)
        if scan.deny_match is None:
            for pattern in deny:
                if pattern.search(body):
                    scan.deny_match = f"{pattern.pattern} (in {path.relative_to(source_dir)})"
                    break
        _scan_inputs(body, source_dir, deny, depth + 1, scan)


def _find_begin_document(text: str) -> int | None:
    for macro in find_macros(text, {"begin"}):
        if macro.argument == "document" and macro.depth == 0:
            return LineIndex(text).line_of(macro.start)
    return None


NO_BEGIN_DOCUMENT = "\\begin{document} is not in the main file (A2)"


def _unstructured(main: Path, lines: list[str]) -> Analysis:
    """Analysis of a main file without ``\\begin{document}`` (e.g. it ``\\input``s the
    document): no format split and no units; only full-mode builds are possible."""
    end = len(lines) + 1
    return Analysis(
        main=main,
        source_dir=main.parent,
        lines=tuple(lines),
        begin_line=end,
        split_line=end,
        split_reason=NO_BEGIN_DOCUMENT,
        preamble_inputs=(),
        includes=(),
        units=(),
        fingerprints=Fingerprints(pre=_sha256(lines), post=_sha256([]), body=_sha256([])),
        fallback_reasons=(NO_BEGIN_DOCUMENT,),
    )


def _backend_reason(backend: str) -> str:
    return f"biblatex backend {backend!r}: only biber is supported"


def _fallback_reasons(text: str) -> list[str]:
    """Unsupported features in comment-free source text (design §1, §6.14)."""
    reasons: list[str] = []
    for macro in find_macros(text, {"usepackage", "RequirePackage"}):
        for package in split_list(macro.argument or ""):
            if package in UNSUPPORTED_PACKAGES:
                reasons.append(f"package {package!r} is not supported")
            if package == "biblatex" and macro.optional:
                backend = re.search(r"backend\s*=\s*(\w+)", macro.optional)
                if backend and backend.group(1) != "biber":
                    reasons.append(
                        f"biblatex backend {backend.group(1)!r}: only biber is supported"
                    )
    for macro in find_macros(text, {"ExecuteBibliographyOptions"}):
        backend = re.search(r"backend\s*=\s*(\w+)", macro.argument or "")
        if backend and backend.group(1) != "biber":
            reasons.append(_backend_reason(backend.group(1)))
    if re.search(r"\\makeglossaries\b", text):
        reasons.append("\\makeglossaries is not supported")
    if re.search(r"\\bibliography\s*\{", text):
        reasons.append("BibTeX (\\bibliography) is not supported; use biblatex with biber")
    # C10: citations outside refsection 0 cannot be patched into the .bcf per run; found
    # here, no build attempt is wasted (the runtime check stays for other ways to start one)
    options = " ".join(
        (m.optional or "") for m in find_macros(text, {"usepackage", "RequirePackage"})
    ) + " ".join(m.argument or "" for m in find_macros(text, {"ExecuteBibliographyOptions"}))
    option = re.search(r"\brefsection\s*=\s*(\w+)", options)
    if (
        (option and option.group(1) != "none")
        or re.search(r"\\begin\s*\{refsection\}", text)
        or re.search(r"\\newrefsection(?![A-Za-z@])", text)
    ):
        reasons.append("biblatex refsections are not supported (citations outside refsection 0)")
    return reasons


def _validate_include_arg(arg: str | None, where: str) -> str:
    if arg is None or not arg.strip():
        raise AnalysisError(f"{where}: \\include without an argument")
    arg = arg.strip()
    pure = PurePosixPath(arg)
    if pure.is_absolute() or re.match(r"^[A-Za-z]:", arg) or ".." in pure.parts:
        raise AnalysisError(
            f"{where}: \\include{{{arg}}}: absolute paths and '..' are not supported "
            "(the unit aux file would be written outside the build directory)"
        )
    if re.search(r"\s", arg):
        raise AnalysisError(
            f"{where}: \\include{{{arg}}}: file names with spaces are not supported"
        )
    return arg


def _first_command(text: str) -> str | None:
    """Name of the first control word of comment-free ``text`` if it starts with one."""
    pos = skip_space(text, 0)
    m = re.compile(r"\\([A-Za-z@]+\*?)").match(text, pos)
    return m.group(1) if m else None


def _group_units(includes: list[Include], warnings: list[str]) -> list[CompilationUnit]:
    groups: list[list[Include]] = []
    for inc in includes:
        if inc.headed or not groups:
            if not inc.headed:
                warnings.append(
                    f"first include {inc.arg!r} does not start with a chapter-level heading (A5); "
                    "it forms its own compilation unit"
                )
            groups.append([inc])
        else:
            groups[-1].append(inc)
    return [CompilationUnit(i, tuple(g)) for i, g in enumerate(groups, start=1)]


def analyse(config: Config) -> Analysis:
    """Analyse the project of ``config.main`` (design §6.1)."""
    if config.main is None:
        raise AnalysisError("no main file")
    main = config.main
    source_dir = main.parent
    raw = read_source(main)
    lines = split_lines(raw)
    clean = strip_comments(raw)
    clean_lines = split_lines(clean)
    begin = _find_begin_document(clean)
    if begin is None:
        return _unstructured(main, lines)

    # 1.-2. preamble, inlined inputs, split point
    deny = [re.compile(p) for p in (*DENY_SPLIT, *config.split_before)]
    pre_clean = clean_lines[: begin - 1]
    depths = depth_at_line_starts(pre_clean)
    open_ifs = open_conditional_at_line_starts(pre_clean)
    split, reason, found = begin, "\\begin{document}", False
    input_files: list[Path] = []
    inputs_by_line: dict[int, list[str]] = {}
    preamble_texts: list[str] = []
    for lineno, line in enumerate(pre_clean, start=1):
        scan = _InputScan()
        _scan_inputs(line, source_dir, deny, 0, scan)
        input_files += [f for f in scan.files if f not in input_files]
        inputs_by_line[lineno] = scan.texts
        preamble_texts += [line, *(strip_comments(t) for t in scan.texts)]
        if found:
            continue
        match = next((p.pattern for p in deny if p.search(line)), None) or scan.deny_match
        if match is not None:
            # move to the start of the enclosing top-level statement (S1): out of brace
            # groups and out of open conditionals (the format must not end inside an \if)
            start, moved = lineno, True
            while moved:
                moved = False
                while start > 1 and depths[start - 1] > 0:
                    start, moved = start - 1, True
                if open_ifs[start - 1]:
                    start, moved = open_ifs[start - 1], True
            split, reason, found = start, match, True

    upto_begin = "".join(clean_lines[:begin])  # \documentclass may share the begin line
    classes = find_macros(upto_begin, {"documentclass"})
    class_line = LineIndex(upto_begin).line_of(classes[0].start) if classes else 0
    structure_reasons: list[str] = []
    if split <= class_line:
        structure_reasons.append(
            "the format split point is not after \\documentclass (same line?); "
            "put \\documentclass on its own line"
        )

    # 3. includes of the body (up to \end{document}), compilation units
    body_text = "".join(clean_lines[begin - 1 :])
    end_doc = next(
        (m.start for m in find_macros(body_text, {"end"}) if m.argument == "document"),
        len(body_text),
    )
    body_text = body_text[:end_doc]
    index = LineIndex(body_text)
    headings = {*UNIT_HEADINGS, *config.unit_headings}
    first_commands: list[str | None] = []
    warnings: list[str] = []
    reasons: list[str] = list(structure_reasons)
    includes: list[Include] = []
    unit_texts: list[str] = []
    for macro in find_macros(body_text, {"include"}):
        lineno = begin - 1 + index.line_of(macro.start)
        where = f"{main.name}:{lineno}"
        if macro.depth > 0:
            reason = f"{where}: \\include inside a group is not supported (A2)"
            reasons += [] if reason in reasons else [reason]
            continue
        arg = _validate_include_arg(macro.argument, where)
        if any(inc.name == include_name(arg) for inc in includes):
            raise AnalysisError(f"{where}: \\include{{{arg}}} appears twice")
        path = source_dir / f"{include_name(arg)}.tex"
        if not path.is_file():
            raise AnalysisError(
                f"{where}: included file not found: {path} (LaTeX would skip it with a "
                "warning; create the file or remove the \\include)"
            )
        # a nested \include is left to LaTeX ("\include cannot be nested"): the text may
        # also contain it in \verb or a verbatim environment
        unit_clean = strip_comments(read_source(path))
        unit_texts.append(unit_clean)
        first_commands.append(_first_command(unit_clean))
        includes.append(Include(arg, path, lineno, headed=False))
    if not any(cmd in headings for cmd in first_commands):  # article-like class (no \chapter)
        headings |= set(SECTION_HEADINGS)
    includes = [
        Include(inc.arg, inc.path, inc.line, cmd in headings, cmd if cmd in headings else None)
        for inc, cmd in zip(includes, first_commands, strict=True)
    ]
    units = _group_units(includes, warnings)

    # 4. fingerprints
    def part(first: int, last: int) -> list[str]:  # main lines first..last (1-based, inclusive)
        out: list[str] = []
        for n in range(first, last + 1):
            out.append(lines[n - 1])
            out += inputs_by_line.get(n, [])
        return out

    fingerprints = Fingerprints(
        pre=_sha256(part(1, split - 1)),
        post=_sha256(part(split, begin - 1)),
        body=_sha256(lines[begin - 1 :]),
    )

    # 5. unsupported features
    reasons += _fallback_reasons("".join(preamble_texts))
    reasons += [r for r in _fallback_reasons(body_text) if r not in reasons]
    for text in unit_texts:
        reasons += [r for r in _fallback_reasons(text) if r not in reasons]

    return Analysis(
        main=main,
        source_dir=source_dir,
        lines=tuple(lines),
        begin_line=begin,
        split_line=split,
        split_reason=reason,
        preamble_inputs=tuple(input_files),
        includes=tuple(includes),
        units=tuple(units),
        fingerprints=fingerprints,
        fallback_reasons=tuple(reasons),
        warnings=tuple(warnings),
    )
