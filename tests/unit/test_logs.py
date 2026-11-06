from chapmk.logs import (
    compose_log,
    first_error,
    format_preamble,
    map_paths,
    printed_log,
    split_segments,
)


def test_map_paths() -> None:
    assert map_paths("/b/src/./a.tex:3: x", [("/b/src", "/s")]) == "/s/./a.tex:3: x"


def test_first_error() -> None:
    log = (
        "This is pdfTeX\n(./a.tex\n./ch/a.tex:12: Undefined control sequence.\n! Emergency stop.\n"
    )
    assert first_error(log) == "./ch/a.tex:12: Undefined control sequence."
    assert first_error("! LaTeX Error: File `x.sty' not found.\n") == (
        "! LaTeX Error: File `x.sty' not found."
    )
    assert first_error("all fine\n(see the transcript file)\n") is None
    # no error line anywhere: the last line of the program output
    assert first_error("", "pdflatex: x\nmiktex: package installation failed\n\n") == (
        "miktex: package installation failed"
    )


def test_first_error_behind_a_generic_stop() -> None:
    """A file on the command line that does not exist: the log (opened later) holds only
    "! Emergency stop."; the cause is in the terminal output (TeX Live and MiKTeX alike)."""
    log = "**&pdflatex mylatexformat.ltx pre.tex\n\n! Emergency stop.\n<*> &pdflatex\n"
    output = (
        "entering extended mode\n! I can't find file `mylatexformat.ltx'.\n"
        "<*> &pdflatex mylatexformat.ltx\n! Emergency stop.\n"
        "!  ==> Fatal error occurred, no output PDF file produced!\n"
    )
    assert first_error(log, output) == "! I can't find file `mylatexformat.ltx'."
    assert first_error(log) == "! Emergency stop."
    assert first_error(log, "! Emergency stop.\n") == "! Emergency stop."
    # a specific error in the log wins over the terminal output
    specific = "./ch/a.tex:3: Undefined control sequence.\n! Emergency stop.\n"
    assert first_error(specific, output) == "./ch/a.tex:3: Undefined control sequence."


def test_first_error_windows_paths() -> None:
    """Absolute Windows paths (drive letter, spaces) as MiKTeX writes them and as the main
    file is mapped to."""
    for path in (r"D:\a\doc\d.tex", "D:/a/doc/d.tex", r"C:\My Documents\thesis\ch\a.tex"):
        line = f"{path}:3: Undefined control sequence."
        assert first_error(f"(./x.tex\n{line}\n! Emergency stop.\n") == line


def test_printed_log_keeps_the_first_banner_only() -> None:
    """LaTeX Workshop keeps the text after the last banner: --print-log keeps only the first
    one, so the logs of all runs are parsed; everything else, line endings included, stays."""
    run1 = "This is pdfTeX, Version 3.14 (TeX Live 2026)\r\n(./a.tex\r\nLaTeX Warning: one\r\n)\r\n"
    run2 = "This is pdfTeX, Version 3.14 (MiKTeX 26.5)\n(./b.tex\nLaTeX Warning: two\n)\n"
    log = "%%% chapmk: log of run r1\n" + run1 + "\n%%% chapmk: log of run r2\n" + run2
    out = printed_log(log)
    assert out.count("This is pdfTeX, Version") == 1
    assert out == log.replace("This is pdfTeX, Version 3.14 (MiKTeX 26.5)\n", "")
    assert printed_log(run1) == run1
    assert printed_log("") == ""


def _run_log(name: str, segments: dict[str, str], tail: str = "") -> str:
    """A run log as chapmk.sty writes it: head, a marker line per segment, end marker, tail."""
    head = f"This is pdfTeX, Version 3.14 (preloaded format=pre)\n**main.tex\n(./main.tex\n{name}\n"
    body = "".join(f"chapmk-segment: {seg}\n{text}" for seg, text in segments.items())
    tail = (
        tail
        or "chapmk-segment: end\n(./main.aux) )\n"
        f"Output written on /b/runs/{name}/main.pdf (3 pages, 99 bytes).\n"
    )
    return head + body + tail


def test_split_segments() -> None:
    log = _run_log("r1", {"G0": "[1]\n", "U1": "(./a.tex\nLaTeX Warning: x\n[2])\n", "G1": ""})
    head, slices, tail = split_segments(log) or ("", {}, "")
    assert head.endswith("(./main.tex\nr1\n")
    assert slices == {"G0": "[1]\n", "U1": "(./a.tex\nLaTeX Warning: x\n[2])\n", "G1": ""}
    assert tail.startswith("(./main.aux) )\nOutput written on")
    assert split_segments("This is pdfTeX\nchapmk-segment: G0\n[1]\n") is None  # no end marker
    assert split_segments("old log without markers\n") is None


def test_compose_log_in_document_order() -> None:
    """Head from the run of the first segment, each segment from its run, the tail of the last
    segment's run with the merged PDF's output line; the slices of other runs are dropped."""
    r1 = _run_log(
        "r1", {"G0": "[1]\n", "U1": "(./a.tex\nWarning A1\n[2])\n", "G1": "", "U2": "", "G2": ""}
    )
    r2 = _run_log(
        "r2",
        {"G0": "[1]\n", "U1": "", "G1": "", "U2": "(./b.tex\nWarning B2\n[3])\n", "G2": "[4]\n"},
    )
    sources = [("G0", "r1"), ("U1", "r1"), ("G1", "r1"), ("U2", "r2"), ("G2", "r2")]
    out = compose_log(
        {"r1": r1, "r2": r2}, sources, output="Output written on main.pdf (4 pages, 7 bytes)."
    )
    assert out is not None
    assert out.count("This is pdfTeX") == 1 and "\nr1\n" in out and "\nr2\n" not in out
    assert out.index("Warning A1") < out.index("Warning B2") < out.index("[4]")
    assert "chapmk-segment" not in out
    assert out.endswith("(./main.aux) )\nOutput written on main.pdf (4 pages, 7 bytes).\n")
    # a run without markers (older chapmk) or a missing slice: no composed log
    assert compose_log({"r1": r1, "r2": "plain log\n"}, sources) is None
    assert compose_log({"r1": r1, "r2": r2}, [*sources, ("U3", "r2")]) is None
    assert compose_log({}, []) is None


def test_format_preamble_inserted_after_the_main_file_opens() -> None:
    fmt = (
        "This is pdfTeX, Version 3.14 (INITEX)\n**&pdflatex mylatexformat.ltx /s/main.tex\n"
        "(/t/mylatexformat.ltx (/s/main.tex (/t/book.cls\nPackage foo Warning: early\n)\n"
        "Beginning to dump on file pre.fmt\n (format=pre 2026.11.6)\n"
    )
    pre = format_preamble(fmt)
    assert (
        pre
        == "(/t/mylatexformat.ltx (/s/main.tex (/t/book.cls\nPackage foo Warning: early\n)\n))\n"
    )
    assert format_preamble("no command line\n") == ""
    r1 = _run_log("r1", {"G0": "[1]\n"})
    out = compose_log({"r1": r1}, [("G0", "r1")], pre) or ""
    assert (
        out.index("(./main.tex\n") < out.index("Package foo Warning: early") < out.index("\nr1\n")
    )
