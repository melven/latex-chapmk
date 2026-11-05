from chapmk.logs import first_error, map_paths, printed_log


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
