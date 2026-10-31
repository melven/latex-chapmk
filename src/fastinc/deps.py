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
_ABX_NOT_DATA = {"cite", "segm", "backref", "refcontext"}
_BBL_ENTRY = re.compile(r"^\s*\\entry\{([^}]*)\}")
_DELIMS = "{},[] \t\r\n"
_TOKENS = re.compile(r"[{},\[\]\s]+")
#: files never scanned for keys
_BINARY_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".eps", ".ps", ".gz", ".zip"}
#: commands that typeset a derived list file (their segment depends on all its content)
_LIST_READERS = re.compile(
    r"\\(tableofcontents|listof[A-Za-z]*|listoftodos|printbibliography|bibliography"
    r"|printnomenclature|printindex|@starttoc|minitoc|printglossar[a-z]*)(?![A-Za-z@])"
)


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
    is referenced if it occurs delimited by ``{ } , [ ]`` or whitespace. Comments count too
    (a safe over-approximation). Keys containing a delimiter are searched as substrings."""

    def __init__(self, texts: Iterable[str]) -> None:
        self.texts = list(texts)
        self.tokens: set[str] = set()
        for text in self.texts:
            self.tokens.update(_TOKENS.split(text))

    def references(self, key: str) -> bool:
        name = key[2:]
        if any(c in _DELIMS for c in name):
            return any(name in text for text in self.texts)
        return name in self.tokens

    def reads_lists(self) -> bool:
        """Whether the texts typeset a derived list (ToC, bibliography, nomenclature, ...)."""
        return any(_LIST_READERS.search(text) for text in self.texts)


def imports(scan: TokenScan, values: Mapping[str, str]) -> dict[str, str]:
    """Referenced keys among ``values`` with their value hashes (stored at compile time)."""
    return {key: value for key, value in values.items() if scan.references(key)}


def changed_imports(
    stored: Mapping[str, str], scan: TokenScan, values: Mapping[str, str]
) -> list[str]:
    """Keys whose value differs from the one stored at compile time: referenced keys that
    are defined now or were defined then (undefined counts as a value)."""
    keys = set(stored) | {k for k in values if k not in stored and scan.references(k)}
    return sorted(k for k in keys if stored.get(k, UNDEFINED) != values.get(k, UNDEFINED))
