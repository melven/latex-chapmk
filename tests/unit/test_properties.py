"""Property tests (hypothesis) of the parsers that split or rewrite text files: line splitting,
byte round trip of sources, aux statements, list-file sections, ``.bcf`` patching."""

import re
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from chapmk.analysis import encode_source, read_source
from chapmk.aux import statements
from chapmk.canon import splice_list, unit_sections
from chapmk.texsource import split_lines, text_lines
from chapmk.tools import citekey_lines, patch_bcf

# characters that line splitters treat differently: CR, form feed, vertical tab, NEL, U+2028/9
_LINE_CHARS = st.sampled_from(
    ["a", " ", "\\", "{", "}", "%", "\r", "\f", "\v", "\x85", "\u2028", "\u2029", "\xe4"]
)
TEXT = st.lists(st.one_of(_LINE_CHARS, st.just("\n"), st.just("\r\n")), max_size=40).map("".join)
# one line without a line ending (no "\n", no trailing "\r")
LINE = st.lists(_LINE_CHARS, max_size=12).map("".join).filter(lambda s: not s.endswith("\r"))


@given(TEXT)
def test_split_lines_round_trip(text: str) -> None:
    lines = split_lines(text)
    assert "".join(lines) == text
    assert all(line.endswith("\n") and "\n" not in line[:-1] for line in lines[:-1])
    assert len(lines) == text.count("\n") + (not text.endswith("\n") and text != "")


@given(st.lists(LINE, max_size=8), st.sampled_from(["\n", "\r\n"]))
def test_text_lines_inverse_of_join(lines: list[str], ending: str) -> None:
    """C12: LF and CRLF files give the same lines; other separators stay inside a line."""
    assert text_lines("".join(line + ending for line in lines)) == lines
    if lines and lines[-1]:  # no final line ending (an empty last line would be one)
        assert text_lines(ending.join(lines)) == lines


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.binary(max_size=64))
def test_read_source_byte_round_trip(tmp_path: Path, data: bytes) -> None:
    """Invalid UTF-8, CRLF and NUL bytes survive read_source/encode_source unchanged."""
    path = tmp_path / "f.tex"
    path.write_bytes(data)
    assert encode_source(read_source(path)) == data


# --- aux statements ------------------------------------------------------------------------------
# escaped braces and backslashes are two characters, so they never escape a following token
_ESCAPED = st.sampled_from(["\\{", "\\}", "\\\\", "\\a"])
_PLAIN = st.sampled_from(["x", " ", "@", "%"])


def _group(inner: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
    return st.lists(st.one_of(inner, _ESCAPED, _PLAIN, st.just("\n")), max_size=5).map(
        lambda parts: "{" + "".join(parts) + "}"
    )


GROUP = st.recursive(_group(st.nothing()), _group, max_leaves=10)
# a statement: a command word, then groups; line breaks only inside groups
STATEMENT = st.builds(
    lambda name, groups: "\\" + name + "".join(groups),
    st.sampled_from(["newlabel", "@setckpt", "LT@i", "abx@aux@cite"]),
    st.lists(GROUP, min_size=1, max_size=3),
)


@given(st.lists(STATEMENT, max_size=6))
def test_aux_statements_rejoin_balanced_lines(stmts: list[str]) -> None:
    """S8: statements spanning several lines (``\\@setckpt``) are joined again, escaped braces
    do not count."""
    lines = "\n".join(stmts).split("\n") if stmts else []
    assert statements(lines) == stmts


@given(st.lists(st.sampled_from(["x", "{", "}", "\\{", "\\}"]), max_size=12))
def test_aux_statements_keep_every_line(lines: list[str]) -> None:
    """Unbalanced input loses no line: the statements are a partition of the lines."""
    assert "\n".join(statements(lines)) == "\n".join(lines)


# --- list files ----------------------------------------------------------------------------------
_ENTRY = st.sampled_from(
    ["\\contentsline {section}{x}{1}\n", "\\relax \n", "y\r\n", "\\chapmk@lmark {U9}x\n"]
)
_ENTRIES = st.lists(_ENTRY, max_size=3)


@st.composite
def list_file(draw: st.DrawFn) -> tuple[str, dict[str, list[str]]]:
    """A list file with marked unit sections (as chapmk.sty writes them) and its sections."""
    out, sections = draw(_ENTRIES), {}
    for k in range(1, draw(st.integers(0, 4)) + 1):
        out += [f"\\chapmk@lmark {{/G{k - 1}}}\n"] + draw(_ENTRIES)
        sections[f"U{k}"] = draw(_ENTRIES)
        out += [f"\\chapmk@lmark {{U{k}}}\n", *sections[f"U{k}"], f"\\chapmk@lmark {{/U{k}}}\n"]
    return "".join(out + draw(_ENTRIES)), sections


@given(list_file(), st.data())
def test_splice_list_replaces_exactly_the_given_sections(
    base_sections: tuple[str, dict[str, list[str]]], data: st.DataObject
) -> None:
    base, sections = base_sections
    assert unit_sections(base) == sections
    assert splice_list(base, sections) == base
    assert splice_list(base, {}) == base
    segs = data.draw(st.lists(st.sampled_from(sorted(sections)), unique=True)) if sections else []
    new = {seg: data.draw(st.lists(_ENTRY.filter(lambda e: "lmark" not in e))) for seg in segs}
    out = splice_list(base, new)
    assert out is not None
    assert unit_sections(out) == {**sections, **new}
    assert splice_list(base, {f"U{len(sections) + 1}": []}) is None  # no markers


# --- .bcf ----------------------------------------------------------------------------------------
_ORDER = re.compile(r'order="(\d+)"')


@st.composite
def citations(draw: st.DrawFn) -> list[tuple[str, str, int]]:
    """(segment, key, original order) per citekey element, in document order."""
    out: list[tuple[str, str, int]] = []
    for seg in draw(st.lists(st.sampled_from(["G0", "U1", "U2", "U3"]), max_size=4)):
        for order in sorted(draw(st.lists(st.integers(1, 3), max_size=3))):
            out.append((seg, draw(st.sampled_from(["a", "b", "c"])), order))
    return out


def _bcf(elements: list[str]) -> str:
    return (
        '<?xml version="1.0"?>\n  <bcf:section number="0">\n'
        + "".join(e + "\n" for e in elements)
        + "  </bcf:section>\n"
    )


def _element(order: int, key: str) -> str:
    return f'    <bcf:citekey order="{order}">{key}</bcf:citekey>'


@given(citations(), st.integers(0, 3))
def test_patch_bcf_renumbers_per_citation_command(
    cites: list[tuple[str, str, int]], old: int
) -> None:
    """§6.10: one order number per citation command (segment and original order), counted
    from 1 in the given order; keys and their order are kept; the patch is idempotent."""
    elements = [(seg, _element(order, key)) for seg, key, order in cites]
    # any .bcf (here: other keys, or none) gets exactly these elements
    for bcf in (_bcf([]), _bcf([_element(1, "z")] * old)):
        out = patch_bcf(bcf, elements)
        lines = citekey_lines(out)
        assert [re.sub(r'order="\d+"', "", x) for x in lines] == [
            re.sub(r'order="\d+"', "", e) for _, e in elements
        ]
        orders = [int(_ORDER.search(x).group(1)) for x in lines]  # type: ignore[union-attr]
        commands = [(seg, order) for seg, _, order in cites]
        expected = [
            1 + sum(commands[j] != commands[j - 1] for j in range(1, i + 1))
            for i in range(len(commands))
        ]
        assert orders == expected
        assert patch_bcf(out, list(zip([s for s, _ in elements], lines, strict=True))) == out
