from pathlib import Path

import pytest

from chapmk.analysis import analyse
from chapmk.config import Config
from chapmk.errors import AnalysisError

PREAMBLE = """\\documentclass{scrbook}
\\usepackage{tikz}
\\usetikzlibrary{external}
\\usepackage{hyperref}
\\ifdraft{%
\\tikzexternalize[prefix=x/]
}{}
"""
BODY = """\\begin{document}
\\tableofcontents
\\include{ch/a}
\\include{ch/a2}
Glue.
\\include{ch/b}
\\end{document}
\\include{after-end}
"""


def make(
    tmp_path: Path,
    preamble: str = PREAMBLE,
    body: str = BODY,
    files: dict[str, str] | None = None,
    newline: str = "\n",
) -> Config:
    files = (
        files
        if files is not None
        else {
            "ch/a.tex": "% comment\n\\chapter{A}\n",
            "ch/a2.tex": "\\section{A2 continues}\n",
            "ch/b.tex": "  \\addchap*{B}\n",
        }
    )
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    main = tmp_path / "thesis.tex"
    main.write_bytes((preamble + body).replace("\n", newline).encode())
    return Config(main=main)


def test_split_at_start_of_group_and_units(tmp_path: Path) -> None:
    a = analyse(make(tmp_path))
    assert a.begin_line == 8
    assert a.split_line == 5  # \ifdraft{ line, not the \tikzexternalize line inside the group
    assert "tikzexternalize" in a.split_reason
    assert [i.arg for i in a.includes] == ["ch/a", "ch/a2", "ch/b"]
    assert [i.line for i in a.includes] == [10, 11, 13]
    assert [i.headed for i in a.includes] == [True, False, True]
    assert [[i.arg for i in u.includes] for u in a.units] == [["ch/a", "ch/a2"], ["ch/b"]]
    assert [(i.heading, i.resets) for i in a.includes] == [
        ("chapter", "chapter"),
        (None, None),
        ("addchap*", None),
    ]
    assert a.jobname == "thesis" and a.newline == "\n"
    assert a.fallback_reasons == () and a.warnings == ()


def test_split_defaults_to_begin_document(tmp_path: Path) -> None:
    a = analyse(make(tmp_path, preamble="\\documentclass{book}\n"))
    assert (a.split_line, a.begin_line) == (2, 2)


def test_split_by_config_regex_and_by_input_file(tmp_path: Path) -> None:
    pre = "\\documentclass{book}\n\\input{setup}\n\\usepackage{foo}\n"
    cfg = make(
        tmp_path,
        preamble=pre,
        files={
            "setup.tex": "\\makeindex\n",
            "ch/a.tex": "\\chapter{A}",
            "ch/a2.tex": "\\chapter{A2}",
            "ch/b.tex": "\\chapter{B}",
        },
    )
    a = analyse(cfg)
    assert a.split_line == 2 and "setup.tex" in a.split_reason
    assert a.preamble_inputs == (tmp_path / "setup.tex",)
    assert any("makeindex" in r for r in a.fallback_reasons)
    a2 = analyse(Config(main=cfg.main, split_before=(r"\\usepackage\{foo\}",)))
    assert a2.split_line == 2  # the input file still matches first


def test_commented_deny_pattern_is_ignored(tmp_path: Path) -> None:
    a = analyse(make(tmp_path, preamble="\\documentclass{book}\n% \\tikzexternalize\n"))
    assert a.split_line == a.begin_line == 3


def test_fingerprints(tmp_path: Path) -> None:
    cfg = make(tmp_path)
    f1 = analyse(cfg).fingerprints
    main = cfg.main
    assert main is not None
    main.write_text(main.read_text().replace("Glue.", "Glue!"))
    f2 = analyse(cfg).fingerprints
    assert (f1.pre, f1.post) == (f2.pre, f2.post) and f1.body != f2.body
    main.write_text(main.read_text().replace("{hyperref}", "[final]{hyperref}"))
    f3 = analyse(cfg).fingerprints
    assert f3.pre != f2.pre and f3.post == f2.post


def test_crlf_lines_are_kept(tmp_path: Path) -> None:
    a = analyse(make(tmp_path, newline="\r\n"))
    assert a.newline == "\r\n" and all(line.endswith("\r\n") for line in a.lines)
    assert a.split_line == 5


@pytest.mark.parametrize(
    ("preamble", "reason"),
    [
        ("\\usepackage{cleveref,amsmath}\n", "cleveref"),
        ("\\usepackage[backend=bibtex]{biblatex}\n", "only biber"),
        ("\\ExecuteBibliographyOptions{backend = bibtex8}\n", "only biber"),
        ("\\makeglossaries\n", "makeglossaries"),
    ],
)
def test_fallback_reasons(tmp_path: Path, preamble: str, reason: str) -> None:
    a = analyse(make(tmp_path, preamble="\\documentclass{book}\n" + preamble))
    assert any(reason in r for r in a.fallback_reasons), a.fallback_reasons


def test_bibtex_in_body_is_a_fallback_reason(tmp_path: Path) -> None:
    a = analyse(make(tmp_path, body=BODY.replace("Glue.", "\\bibliography{refs}")))
    assert any("BibTeX" in r for r in a.fallback_reasons)


@pytest.mark.parametrize(
    ("include", "message"),
    [
        ("\\include{../x}", "absolute paths and '..'"),
        ("\\include{/abs/x}", "absolute paths"),
        ("\\include{my file}", "spaces"),
        ("\\include{missing}", "not found"),
        ("\\include{ch/a}", "twice"),
    ],
)
def test_include_errors(tmp_path: Path, include: str, message: str) -> None:
    with pytest.raises(AnalysisError, match=message):
        analyse(make(tmp_path, body=BODY.replace("Glue.", include)))


def test_nested_include_and_missing_begin(tmp_path: Path) -> None:
    files = {"ch/a.tex": "\\chapter{A}\\include{x}", "ch/a2.tex": "x", "ch/b.tex": "x"}
    with pytest.raises(AnalysisError, match="nested"):
        analyse(make(tmp_path, files=files))


def test_structures_that_only_allow_full_builds(tmp_path: Path) -> None:
    a = analyse(make(tmp_path, body="\\input{body}\n"))
    assert a.fallback_reasons == ("\\begin{document} is not in the main file (A2)",)
    assert (a.includes, a.units, a.split_line) == ((), (), len(a.lines) + 1)
    b = analyse(make(tmp_path, body=BODY.replace("Glue.", "{\\include{ch/b}}")))
    assert any("inside a group" in r for r in b.fallback_reasons)
    assert [i.arg for i in b.includes] == ["ch/a", "ch/a2", "ch/b"]


def test_first_unheaded_include_warns(tmp_path: Path) -> None:
    files = {"ch/a.tex": "text", "ch/a2.tex": "\\chapter{x}", "ch/b.tex": "\\chapter*{y}"}
    a = analyse(make(tmp_path, files=files))
    assert len(a.units) == 3 and "A5" in a.warnings[0]


def test_custom_heading(tmp_path: Path) -> None:
    files = {"ch/a.tex": "\\chapter{A}", "ch/a2.tex": "\\mychapter{x}", "ch/b.tex": "\\chapter{B}"}
    cfg = make(tmp_path, files=files)
    assert len(analyse(cfg).units) == 2
    assert len(analyse(Config(main=cfg.main, unit_headings=("mychapter",))).units) == 3


def test_sections_head_units_only_without_chapters(tmp_path: Path) -> None:
    files = {"ch/a.tex": "\\section{A}", "ch/a2.tex": "\\section*{x}", "ch/b.tex": "\\addsec{B}"}
    assert len(analyse(make(tmp_path, files=files)).units) == 3  # article-like: sections head
    files["ch/b.tex"] = "\\chapter{B}"
    a = analyse(make(tmp_path, files=files))
    assert [[i.arg for i in u.includes] for u in a.units] == [["ch/a", "ch/a2"], ["ch/b"]]


def test_split_must_follow_documentclass(tmp_path: Path) -> None:
    main = tmp_path / "d.tex"
    main.write_text("\\documentclass{article}\\begin{document}x\\end{document}\n")
    a = analyse(Config(main=main))
    assert any("documentclass" in r for r in a.fallback_reasons)


def test_split_moves_out_of_open_conditional(tmp_path: Path) -> None:
    main = tmp_path / "m.tex"
    main.write_text(
        "\\documentclass{book}\n\\usepackage{tikz}\n\\newif\\ifext\n\\extfalse\n"
        "\\ifext\n  \\tikzexternalize\n\\fi\n\\begin{document}\nx\n\\end{document}\n"
    )
    a = analyse(Config(main=main))
    assert a.split_line == 5 and "tikzexternalize" in a.split_reason


def test_split_before_pdf_object_creators(tmp_path: Path) -> None:
    main = tmp_path / "m.tex"
    main.write_text(
        "\\documentclass{book}\n\\usepackage{tikz}\n\\usetikzlibrary{\n  calc,\n  fadings,\n}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    a = analyse(Config(main=main))
    assert a.split_line == 3 and "fadings" in a.split_reason
