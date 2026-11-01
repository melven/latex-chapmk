from fastinc.texsource import (
    LineIndex,
    control_sequences,
    depth_at_line_starts,
    find_macros,
    read_group,
    read_optional,
    split_lines,
    split_list,
    strip_comment,
    strip_comments,
)


def test_strip_comment_plain_and_escaped() -> None:
    assert strip_comment("a % b\n") == "a \n"
    assert strip_comment(r"50\% of it % c") == r"50\% of it "
    assert strip_comment("\\\\% c") == "\\\\"  # \\ then a real comment
    assert strip_comment("no comment") == "no comment"


def test_strip_comments_keeps_lines() -> None:
    text = "a % x\nb\n% only\n"
    assert strip_comments(text) == "a \nb\n\n"


def test_control_sequences_depth_and_star() -> None:
    cs = list(control_sequences(r"\a{\b{\c}}\chapter*{x}\%"))
    assert [(c.name, c.depth) for c in cs] == [
        ("a", 0),
        ("b", 1),
        ("c", 2),
        ("chapter*", 0),
        ("%", 0),
    ]


def test_read_group_and_optional() -> None:
    text = r"\x [a{]}b] {c{d}\}e}"
    opt, pos = read_optional(text, 2)
    assert opt == "a{]}b"
    assert read_group(text, pos) == (r"c{d}\}e", len(text))
    assert read_group("x", 0) is None
    assert read_optional("{a}", 0) == (None, 0)


def test_find_macros() -> None:
    text = "\\usepackage[final]{hyperref}\n{\\include{ch/a}}\\include {b}"
    pk = find_macros(text, {"usepackage"})
    assert (pk[0].optional, pk[0].argument) == ("final", "hyperref")
    inc = find_macros(text, {"include"})
    assert [(m.argument, m.depth) for m in inc] == [("ch/a", 1), ("b", 0)]


def test_line_index_and_depths() -> None:
    idx = LineIndex("a\nbc\n\nd")
    assert [idx.line_of(o) for o in (0, 1, 2, 4, 5, 6)] == [1, 1, 2, 2, 3, 4]
    assert depth_at_line_starts(["\\x{%\n", "a\n", "}\n", "\\{\n"]) == [0, 1, 1, 0]


def test_split_list() -> None:
    assert split_list(" a, b ,,c") == ["a", "b", "c"]


def test_split_lines_only_at_newline() -> None:
    assert split_lines("a\r\nb\x0cc\n\nd") == ["a\r\n", "b\x0cc\n", "\n", "d"]
    assert split_lines("") == []
    assert split_lines("x\n") == ["x\n"]


def test_backslash_at_line_end_does_not_stop_scanning() -> None:
    text = "a\\\n\\include{x}\\"
    assert [c.name for c in control_sequences(text)] == ["\n", "include"]


def test_open_conditionals() -> None:
    from fastinc.texsource import open_conditional_at_line_starts

    lines = [
        "\\newif\\ifext\n",
        "\\extfalse\n",
        "\\ifext\n",
        "  \\ifx\\a\\b x\\else y\\fi\n",
        "  \\tikzexternalize\n",
        "\\fi\n",
        "\\iftoggle{t}{a}{b}\n",  # etoolbox command, not a conditional
    ]
    assert open_conditional_at_line_starts(lines) == [0, 0, 0, 3, 3, 3, 0]
