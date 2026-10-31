from fastinc.logs import first_error, map_paths


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
