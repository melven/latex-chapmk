"""Unit tests for lint.py: A1 lint, lint cache, glue hints."""

from pathlib import Path

from chapmk.lint import lint_text


def _cmds(text: str, allow: tuple[str, ...] = ()) -> list[tuple[int, str, bool]]:
    return [(h.line, h.command, h.is_global) for h in lint_text(text, "u.tex", allow)]


def test_lint_local_commands_outside_groups() -> None:
    assert _cmds("\\chapter{A}\n\\setlength{\\parindent}{0pt}\n") == [(2, "\\setlength", False)]
    assert _cmds("\\begin{table}\\setlength{\\tabcolsep}{1pt}\\end{table}") == []
    assert _cmds("{\\setlength{\\parskip}{0pt} x}") == []
    assert _cmds("\\begingroup\\def\\x{1}\\endgroup") == []
    # braces after a control word, } or ] are arguments, not groups
    assert _cmds("\\ifdraft{\\def\\x{1}}{}") == [(1, "\\def", False)]
    assert _cmds("\\foo[o]{\\let\\a\\b}") == [(1, "\\let", False)]
    # inside an argument inside a real group: grouped
    assert _cmds("\\begin{figure}\\ifdraft{\\def\\x{1}}{}\\end{figure}") == []
    # after the group closed
    assert _cmds("{\\small x}\n\\def\\y{2}") == [(2, "\\def", False)]


def test_lint_global_commands_comments_verbatim_allow() -> None:
    assert _cmds("{\\global\\def\\x{1}}") == [(1, "\\global\\def", True)]
    assert _cmds("\\begin{table}\\newcounter{c}\\end{table}") == [(1, "\\newcounter", True)]
    assert _cmds("% \\def\\x{1}\ntext 50\\% \\pagestyle{empty}") == [(2, "\\pagestyle", True)]
    # the page colour is set globally (S18), also inside a group
    assert _cmds("{\\pagecolor{yellow}}\\nopagecolor") == [
        (1, "\\pagecolor", True),
        (1, "\\nopagecolor", True),
    ]
    assert _cmds("\\begin{verbatim}\n\\def\\x{1}\n\\end{verbatim}\n\\verb|\\def| x") == []
    assert _cmds("\\setlength{\\a}{1pt}", allow=("\\setlength",)) == []
    # configured verbatim environments and short verbatim characters (pgf manual)
    code = "\\begin{codeexample}[preamble={\\usetikzlibrary{x}}]\n\\def\\a{}\n\\end{codeexample}"
    assert _cmds(code) != [] and lint_text(code, "u.tex", verbatim=("codeexample",)) == []
    short = "write |\\def\\pgfsysdriver{x}| somewhere\n|unclosed \\pagestyle{empty}"
    assert [h.command for h in lint_text(short, "u.tex", shortverb=("|",))] == ["\\pagestyle"]
    assert "wrap it in a group" in lint_text("\\def\\x{}", "u.tex")[0].message()
    assert "move it to the preamble" in lint_text("\\appendix", "u.tex")[0].message()


def test_lint_cache(tmp_path: Path) -> None:
    """Cached hits equal fresh ones; a changed file or changed options are linted again."""
    from chapmk.lint import lint_files

    (tmp_path / "a.tex").write_text("\\chapter{A}\n\\def\\x{1}\n")
    cache: dict[str, list[list[object]]] = {}
    first = lint_files(tmp_path, ["a.tex"], cache=cache)  # type: ignore[arg-type]
    assert len(cache) == 1 and first
    assert lint_files(tmp_path, ["a.tex"], cache=cache) == first  # type: ignore[arg-type]
    assert lint_files(tmp_path, ["a.tex"], allow=["def"], cache=cache) == []  # type: ignore[arg-type]
    (tmp_path / "a.tex").write_text("\\chapter{A}\n")
    assert lint_files(tmp_path, ["a.tex"], cache=cache) == []  # type: ignore[arg-type]
    assert len(cache) == 3


def test_glue_hints() -> None:
    """Slow glue blocks: the part from the first chapter-level heading or list command can be
    \\include'd (state commands before it stay; list commands need a units.heading entry);
    otherwise the reason; fast blocks: nothing."""
    from chapmk.lint import glue_hints

    lines = [
        "\\documentclass{book}\n",  # 1
        "\\begin{document}\n",  # 2
        "\\tableofcontents\n",  # 3   G0 (fast)
        "\\include{a}\n",  # 4
        "\\appendix\n",  # 5          G1: \appendix stays, \chapter movable
        "\\chapter{Extra}\n",  # 6
        "\\include{b}\n",  # 7
        "\\backmatter\n",  # 8        G2: as in the reference document
        "\n",  # 9
        "% comment\n",  # 10
        "\\printbibliography\n",  # 11
        "\\include{c}\n",  # 12
        "Some text\\par\n",  # 13      G3: no heading
        "\\end{document}\n",
    ]
    hints = glue_hints(
        "main.tex", lines, 2, [4, 7, 12], {"G0": 0.1, "G1": 0.7, "G2": 1.8, "G3": 0.9}, ["chapter"]
    )
    assert len(hints) == 3
    assert hints[0].startswith("main.tex:5-6: glue (\\appendix) takes 0.7 s")
    assert "lines 6-6 (from \\chapter) moved" in hints[0] and "(lines 5-5 stay)" in hints[0]
    assert hints[1].startswith("main.tex:8-11: glue (\\backmatter) takes 1.8 s")
    assert "lines 11-11 (from \\printbibliography) moved" in hints[1]
    assert '[units] heading = ["printbibliography"] (lines 8-10 stay)' in hints[1]
    assert "no chapter-level heading" in hints[2]
    grouped = ["\\begin{document}\n", "\\chapter{X}\\begingroup\n", "\\include{a}\n"]
    [hint] = glue_hints("m.tex", grouped, 1, [3], {"G0": 1.0}, ["chapter"])
    assert "group or environment is open" in hint
    stateful = ["\\begin{document}\n", "\\chapter{X}\\pagestyle{empty}\n", "\\include{a}\n"]
    [hint] = glue_hints("m.tex", stateful, 1, [3], {"G0": 1.0}, ["chapter"])
    assert "contains \\pagestyle" in hint
