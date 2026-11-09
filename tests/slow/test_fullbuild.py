"""Full-mode build and CLI against real TeX."""

import json
import re
from pathlib import Path

import pytest

from chapmk.cli import main
from chapmk.synctex import read_lines
from chapmk.texdist import detect

pytestmark = pytest.mark.slow


def test_full_build_with_biber_and_nomencl(copy_corpus, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    src = copy_corpus("minimal/S1-format")
    out = tmp_path / "out"
    rc = main(["build", "main.tex", "--full", "--out-dir", str(out), "-v"], cwd=src)
    err = capsys.readouterr().err
    assert rc == 0, err
    assert (out / "main.pdf").is_file() and (out / "main.log").is_file()
    full = src / ".chapmk" / "main" / "full"
    assert (full / "main.bbl").is_file() and (full / "main.nls").is_file()
    assert "stable" in err and "pass 1: changed" in err
    inputs = [line for line in read_lines(out / "main.synctex.gz") if line.startswith("Input:")]
    main_input = detect().synctex_input(src, "main.tex")  # TeX Live: <src>/./main.tex
    assert any(line.endswith(main_input) for line in inputs), inputs[:3]
    assert not any(".chapmk/src" in line for line in inputs)
    assert ".chapmk/src" not in (out / "main.log").read_text()
    # nothing was written into the source directory except the build dir
    assert {p.name for p in src.iterdir()} == {"main.tex", "thesis.bib", "run.sh", ".chapmk"}


def test_full_build_runs_makeindex_for_an_index(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """Full mode runs makeindex on ``<job>.idx`` like latexmk (imakeidx's own call fails
    with -output-directory, found on the pgf manual)."""
    src = tmp_path / "s"
    src.mkdir()
    (src / "d.tex").write_text(
        "\\documentclass{article}\n\\usepackage{makeidx}\\makeindex\n\\begin{document}\n"
        "Alpha\\index{alpha} beta\\index{beta}\n\\printindex\n\\end{document}\n"
    )
    # --full: an index alone no longer forces full mode (incremental builds run makeindex
    # on the canonical .idx)
    assert main(["build", "d.tex", "--full", "-v"], cwd=src) == 0, capsys.readouterr().err
    ind = src / ".chapmk" / "d" / "full" / "d.ind"
    assert ind.is_file() and "alpha" in ind.read_text()


def test_failing_build_keeps_previous_pdf(copy_corpus, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    src = tmp_path / "s"
    src.mkdir()
    (src / "d.tex").write_text("\\documentclass{article}\n\\begin{document}\nok\n\\end{document}\n")
    assert main(["build", "d.tex"], cwd=src) == 0
    pdf = (src / "d.pdf").read_bytes()
    (src / "d.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\undefinedmacro\n\\end{document}\n"
    )
    assert main(["build", "d.tex"], cwd=src) == 1
    err = capsys.readouterr().err
    assert "d.tex:3: Undefined control sequence" in err  # mapped to the user's main file
    assert (src / "d.pdf").read_bytes() == pdf
    assert "Undefined control sequence" in (src / "d.log").read_text()


def test_print_log(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """--print-log (§6.13): the published log on stdout with one banner line (LaTeX Workshop
    parses only the output after the last one), after a success and after a TeX error."""
    src = tmp_path / "s"
    src.mkdir()
    (src / "d.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n\\include{a}\n\\include{b}\n\\end{document}\n"
    )
    (src / "a.tex").write_text("\\chapter{A}A\\ref{nowhere}\n")
    (src / "b.tex").write_text("\\chapter{B}B\n")
    assert main(["build", "d.tex", "-j", "2", "--print-log"], cwd=src) == 0
    out = capsys.readouterr().out
    log = (src / "d.log").read_bytes().decode("utf-8")  # as printed: line endings unchanged
    assert out.count("This is pdfTeX, Version") == 1
    assert "Output written on" in out and "Reference `nowhere' on page" in out
    assert [ln for ln in out.split("\n") if "This is pdfTeX" not in ln] == [
        ln for ln in log.split("\n") if "This is pdfTeX" not in ln
    ]
    (src / "b.tex").write_text("\\chapter{B}\\undefinedmacro\n")
    assert main(["build", "d.tex", "--print-log"], cwd=src) == 1
    captured = capsys.readouterr()
    assert "Undefined control sequence" in captured.out  # the failing run's log
    assert "b.tex:1: Undefined control sequence" in captured.err
    assert main(["build", "d.tex"], cwd=src) == 1
    assert capsys.readouterr().out == ""  # only with --print-log


#: messages a log parser shows: warnings, bad boxes, errors
_MESSAGE = re.compile(r"^(?:(?:LaTeX|Package|Class) .*Warning|(?:Over|Under)full \\[hv]box|! )")
#: summaries at the end of a run: they cover that run's units only, or ask for another run
_SUMMARY = re.compile(
    r"Rerun|may have changed|There were (?:undefined references|multiply-defined labels)"
    r"|Some font shapes were not available|Size substitutions"
    r"|Unused \\captionsetup"  # caption's check at \AtEndDocument
)


def _messages(log: str) -> list[str]:
    return [ln for ln in log.splitlines() if _MESSAGE.match(ln) and not _SUMMARY.search(ln)]


def test_composed_log_matches_a_full_build(copy_corpus, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """§6.13: the log composed from several runs (cold build, incremental runs) has the messages
    of a plain full build in the same order (preamble from the format build, each unit from
    its run), one banner and the merged PDF's output line."""
    src = copy_corpus("thesis")
    assert main(["build", "main.tex"], cwd=src) == 0
    # two units recompiled in parallel runs, the others stay in the cold build's run
    for name, extra in (("ch2", "\\ref{nowhere-two}"), ("ch5", "\\hbox to 1pt{too wide here}")):
        with (src / "chapters" / f"{name}.tex").open("a") as f:
            f.write(f"\n{extra}\n")
    assert main(["build", "main.tex", "-j", "2", "--report", "r.json"], cwd=src) == 0
    report = json.loads((src / "r.json").read_text())
    assert report["mode"] == "incremental" and report["runs"], report
    log = (src / "main.log").read_text()
    assert main(["build", "main.tex", "--full", "--out-dir", str(tmp_path / "full")], cwd=src) == 0
    capsys.readouterr()
    full = (tmp_path / "full" / "main.log").read_text()
    assert _messages(log) == _messages(full)
    assert any("nowhere-two" in m for m in _messages(full))
    assert any(m.startswith("Overfull") for m in _messages(full))
    assert log.count("This is pdfTeX, Version") == 1 and "chapmk-segment" not in log
    pages = re.search(r"^Output written on .*\((\d+) pages", full, re.MULTILINE)
    assert pages and f"({pages.group(1)} pages," in log
    assert f"Output written on {src / 'main.pdf'}" in log


def test_print_log_includes_biber_output(copy_corpus, capsys) -> None:  # type: ignore[no-untyped-def]
    """--print-log (§6.13) also writes the last biber run's output, from which LaTeX Workshop
    takes biber's warnings (here: a missing entry), as latexmk's output contains it;
    incremental (canon/) and full mode (full/)."""
    src = copy_corpus("minimal/S1-format")
    main_tex = src / "main.tex"
    main_tex.write_text(
        main_tex.read_text().replace("\\cite{lamport94}", "\\cite{lamport94,nosuchkey}")
    )
    for extra in ([], ["--full"]):
        assert main(["build", "main.tex", "--print-log", *extra], cwd=src) == 0
        out = capsys.readouterr().out
        assert "INFO - This is Biber" in out, extra
        assert "WARN - I didn't find a database entry for 'nosuchkey'" in out, extra
        assert "INFO - Found BibTeX data source 'thesis.bib'" in out, extra


def test_clean(tmp_path: Path) -> None:
    src = tmp_path / "s"
    src.mkdir()
    (src / "d.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}\n")
    assert main(["build", "d.tex"], cwd=src) == 0
    assert (src / ".chapmk" / "d").is_dir()
    assert main(["clean", "d.tex"], cwd=src) == 0
    assert not (src / ".chapmk").exists()
    (src / "other").mkdir()
    assert main(["clean", "d.tex", "--build-dir", "other"], cwd=src) == 2
    assert (src / "other").is_dir()
