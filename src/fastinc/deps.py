"""Dependency model (PLAN §6.8): imported keys found by a text scan, and their current values.

Keys are namespaced: ``L:<label>`` for ``\\newlabel`` keys, ``C:<citekey>`` for ``.bbl``
entries. A value is a short hash of the whole ``\\newlabel`` argument (number, page, title,
anchor; §6.8.1 item 5), or of the ``.bbl`` entry block plus its position (§6.10) plus the
keyed biblatex aux data of the key (e.g. ``\\abx@aux@number`` with ``defernumbers``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from fastinc.aux import normalize_statement, statements

UNDEFINED = "-"
_NEWLABEL = re.compile(r"^\\newlabel\{(.+?)\}\{(.*)\}\s*$", re.DOTALL)
_ABX_KEYED = re.compile(r"^\\abx@aux@([A-Za-z@]+)\{[^{}]*\}\{([^{}]+)\}")
#: biblatex aux statements that are not data of a key (citations, bookkeeping)
#: (``defaultrefcontext`` names the refcontext, a preamble setting; it is missing in a run
#: without ``.bbl`` and would make every citation look changed once in cold builds)
_ABX_NOT_DATA = {"cite", "segm", "backref", "refcontext", "defaultrefcontext"}
_BBL_ENTRY = re.compile(r"^\s*\\entry\{([^}]*)\}")
_DELIMS = "{},[] \t\r\n"
_TOKENS = re.compile(r"[{},\[\]\s]+")
_HAS_DELIM = re.compile(r"[{},\[\] \t\r\n]")
_LABEL_DEF = re.compile(r"\\label\s*\{[^{}]*\}")
#: files never scanned for keys
_BINARY_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".eps", ".ps", ".gz", ".zip"}
#: commands that typeset a derived list file (their segment depends on all its content)
_LIST_READERS = re.compile(
    r"\\(tableofcontents|listof[A-Za-z]*|listoftodos|printbibliography|bibliography"
    r"|printnomenclature|printindex|@starttoc|minitoc|printglossar[a-z]*)(?![A-Za-z@])"
)


#: list commands with a known derived file (others: all list files)
_LIST_FILES = {
    "tableofcontents": ".toc",
    "minitoc": ".toc",
    "listoffigures": ".lof",
    "listoftables": ".lot",
    "listofalgorithms": ".loalg",
    "listoftodos": ".tdo",
    "printbibliography": ".bbl",
    "bibliography": ".bbl",
    "printnomenclature": ".nls",
}
_STARTTOC_ARG = re.compile(r"\s*\{([A-Za-z]+)\}")


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()[:16]


def label_values(aux_lines: Iterable[list[str]]) -> dict[str, str]:
    """``L:key`` → value hash of the ``\\newlabel`` statements in the given aux files (later
    definitions win, as in LaTeX)."""
    values: dict[str, str] = {}
    for lines in aux_lines:
        for stmt in statements(lines):
            m = _NEWLABEL.match(stmt)
            if m:
                values[f"L:{m.group(1)}"] = short_hash(m.group(2))
    return values


def defined_labels(stmts: Iterable[str]) -> list[str]:
    """``L:key`` of the ``\\newlabel`` statements among ``stmts``."""
    return [f"L:{m.group(1)}" for m in map(_NEWLABEL.match, stmts) if m]


def cite_values(bbl: Path, aux_statements: Iterable[str] = ()) -> dict[str, str]:
    """``C:key`` → hash of ``<position>:<entry block>`` of the key's ``.bbl`` entry and of
    the keyed biblatex aux statements naming the key (``\\abx@aux@number{..}{key}...``)."""
    blocks = _bbl_blocks(bbl)
    data: dict[str, list[str]] = {}
    for stmt in aux_statements:
        m = _ABX_KEYED.match(stmt)
        if m and m.group(1) not in _ABX_NOT_DATA:
            data.setdefault(m.group(2), []).append(normalize_statement(stmt))
    return {
        f"C:{key}": short_hash(
            blocks.get(key, UNDEFINED) + "\0" + "\n".join(sorted(data.get(key, [])))
        )
        for key in blocks.keys() | data.keys()
    }


def _bbl_blocks(bbl: Path) -> dict[str, str]:
    """``key`` → ``<position>:<entry block>`` per entry of a biblatex ``.bbl``."""
    if not bbl.is_file():
        return {}
    values: dict[str, str] = {}
    key: str | None = None
    block: list[str] = []
    for line in bbl.read_text(encoding="utf-8", errors="surrogateescape").splitlines():
        m = _BBL_ENTRY.match(line)
        if m:
            key, block = m.group(1), [line]
        elif key is not None:
            block.append(line)
            if line.strip() == "\\endentry":
                values[key] = f"{len(values)}:" + "\n".join(block)
                key = None
    return values


def read_text(path: Path) -> str | None:
    """Text of a source file for scanning, or None for binary files."""
    if path.suffix.lower() in _BINARY_SUFFIXES or not path.is_file():
        return None
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", "surrogateescape")


class TokenScan:
    """The tokens of some source texts, for finding referenced keys (§6.8.1 item 5): a key
    is referenced if it occurs delimited by ``{ } , [ ]`` or whitespace, except as the argument
    of ``\\label``. Comments count too (a safe over-approximation). Keys containing a delimiter
    are searched as substrings."""

    def __init__(self, texts: Iterable[str]) -> None:
        # a \label{key} defines the key; it is not a reference
        self.texts = [_LABEL_DEF.sub(" ", text) for text in texts]
        self.tokens: set[str] = set()
        for text in self.texts:
            self.tokens.update(_TOKENS.split(text))

    def references(self, key: str) -> bool:
        name = key[2:]
        if any(c in _DELIMS for c in name):
            return any(name in text for text in self.texts)
        return name in self.tokens

    @classmethod
    def stored(cls, tokens: Iterable[str], text: str) -> TokenScan:
        """A scan from its stored tokens and (label-stripped) text, without scanning again."""
        scan = cls([])
        scan.texts = [text]
        scan.tokens = set(tokens)
        return scan

    def referenced(self, keys: Iterable[str]) -> set[str]:
        """The referenced keys among ``keys`` (namespaced). Same result as filtering with
        :meth:`references`, in time linear in the tokens plus the keys containing a
        delimiter (a membership test per token instead of a scan per key)."""
        keys = keys if isinstance(keys, (set, frozenset, dict)) else set(keys)
        found = {k for t in self.tokens for k in (f"L:{t}", f"C:{t}") if k in keys}
        found |= {k for k in keys if _HAS_DELIM.search(k, 2) and self.references(k)}
        return found

    def list_reads(self) -> set[str] | None:
        """Suffixes of the derived list files the texts typeset (``\\printbibliography`` →
        ``.bbl``, ``\\tableofcontents`` → ``.toc``, ...); None if a list command of unknown
        file is used (then all list files count)."""
        out: set[str] = set()
        for text in self.texts:
            for m in _LIST_READERS.finditer(text):
                name = m.group(1)
                if name == "@starttoc":
                    arg = _STARTTOC_ARG.match(text, m.end())
                    if arg is None:
                        return None
                    out.add(f".{arg.group(1)}")
                elif name in _LIST_FILES:
                    out.add(_LIST_FILES[name])
                else:
                    return None
        return out

    def reads_lists(self) -> bool:
        """Whether the texts typeset a derived list (ToC, bibliography, nomenclature, ...)."""
        return any(_LIST_READERS.search(text) for text in self.texts)


def imports(scan: TokenScan, values: Mapping[str, str]) -> dict[str, str]:
    """Referenced keys among ``values`` with their value hashes (stored at compile time)."""
    return {key: values[key] for key in sorted(scan.referenced(values))}


def changed_imports(
    stored: Mapping[str, str], scan: TokenScan, values: Mapping[str, str]
) -> list[str]:
    """Keys whose value differs from the one stored at compile time: referenced keys that
    are defined now or were defined then (undefined counts as a value)."""
    keys = set(stored) | scan.referenced(values)
    return sorted(k for k in keys if stored.get(k, UNDEFINED) != values.get(k, UNDEFINED))
