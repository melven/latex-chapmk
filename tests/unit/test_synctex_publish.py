import gzip
from pathlib import Path

import pytest

from chapmk.publish import copy_bytes, publish
from chapmk.synctex import (
    SyncTexError,
    map_input_paths,
    merge,
    parse,
    read_lines,
    serialise,
    write_lines,
)

SAMPLE = [
    "SyncTeX Version:1",
    "Input:1:/build/src/./main.tex",
    "Input:2:/usr/share/texmf/a.sty",
    "Output:pdf",
    "Content:",
    "!999",
    "{1",
    "[1,8:4736286,47703979:26590338,42967693,0",
    "]",
    "!0",
    "}1",
    "Input:3:/build/src/./ch/a.tex",
    "!1",
    "Postamble:",
    "Count:2",
    "!5",
    "Post scriptum:",
]


def test_offsets_are_recomputed() -> None:
    data = serialise(SAMPLE).decode()
    lines = data.split("\n")
    pos, last = 0, 0
    for line in lines:
        if line.startswith("!"):
            assert int(line[1:]) == pos - last
            last = pos
        pos += len(line) + 1


def test_map_input_paths_keeps_dot_form() -> None:
    mapped = map_input_paths(SAMPLE, [("/build/src", "/home/u/thesis")])
    assert "Input:1:/home/u/thesis/./main.tex" in mapped
    assert "Input:3:/home/u/thesis/./ch/a.tex" in mapped
    assert "Input:2:/usr/share/texmf/a.sty" in mapped
    assert map_input_paths(["Input:1:/build/srcX/a"], [("/build/src", "/x")]) == [
        "Input:1:/build/srcX/a"
    ]
    # MiKTeX on Windows: native paths below the shadow tree
    shadow = [("C:\\b\\src", "C:\\t")]
    assert map_input_paths(["Input:4:C:\\b\\src\\ch\\a.tex"], shadow) == [
        "Input:4:C:\\t\\ch\\a.tex"
    ]


def test_write_read_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "a.synctex.gz"
    write_lines(p, SAMPLE)
    again = read_lines(p)
    assert [line for line in again if not line.startswith("!")] == [
        line for line in SAMPLE if not line.startswith("!")
    ]
    write_lines(tmp_path / "b.synctex.gz", again)
    assert (tmp_path / "b.synctex.gz").read_bytes() == p.read_bytes()  # deterministic gzip


def test_publish_atomic_and_fallback(tmp_path: Path) -> None:
    src = tmp_path / "s.pdf"
    src.write_bytes(b"new")
    target = tmp_path / "out" / "thesis.pdf"
    assert publish(copy_bytes(src), target) == target
    assert target.read_bytes() == b"new"
    assert not list(target.parent.glob(".*chapmk-tmp"))

    calls: list[Path] = []

    def locked(a: Path, b: Path) -> None:  # a viewer locks the regular output names
        calls.append(b)
        if ".chapmk." not in b.name:
            raise PermissionError("locked")
        a.replace(b)

    syn = tmp_path / "out" / "thesis.synctex.gz"
    got = publish(copy_bytes(src), syn, retry_seconds=0.0, replace=locked)
    assert got == tmp_path / "out" / "thesis.chapmk.synctex.gz" and got.read_bytes() == b"new"
    got = publish(copy_bytes(src), target, retry_seconds=0.0, replace=locked)
    assert got.name == "thesis.chapmk.pdf"


def test_publish_propagates_write_errors(tmp_path: Path) -> None:
    def broken(_: Path) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        publish(broken, tmp_path / "x.pdf")


def test_publish_all_writes_everything_before_renaming(tmp_path: Path) -> None:
    """C16: all files are written before the first rename; a failing writer leaves the old
    set and no temporary files."""
    from chapmk.publish import publish_all

    pdf, syn = tmp_path / "main.pdf", tmp_path / "main.synctex.gz"
    pdf.write_text("old pdf")
    syn.write_text("old syn")
    renamed: list[str] = []

    def replace(src: Path, dst: Path) -> None:
        renamed.append(dst.name)
        src.replace(dst)

    def fail(_tmp: Path) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError):
        publish_all([(lambda t: t.write_text("new syn"), syn), (fail, pdf)], replace=replace)
    assert (pdf.read_text(), syn.read_text()) == ("old pdf", "old syn") and renamed == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["main.pdf", "main.synctex.gz"]
    written: list[str] = []

    def writer(text: str, name: str):  # type: ignore[no-untyped-def]
        def write(t: Path) -> None:
            assert renamed == []  # nothing renamed while writing
            written.append(name)
            t.write_text(text)

        return write

    out = publish_all(
        [(writer("new syn", "syn"), syn), (writer("new pdf", "pdf"), pdf)], replace=replace
    )
    assert (
        out == [syn, pdf]
        and written == ["syn", "pdf"]
        and renamed == ["main.synctex.gz", "main.pdf"]
    )
    assert (pdf.read_text(), syn.read_text()) == ("new pdf", "new syn")


def synctex_file(path: Path, main: str, sheets: int) -> None:
    lines = [
        "SyncTeX Version:1",
        f"Input:1:{main}",
        "Input:2:/tex/a.sty",
        "Output:pdf",
        "Magnification:1000",
        "Unit:1",
        "X Offset:0",
        "Y Offset:0",
        "Content:",
    ]
    for n in range(1, sheets + 1):
        lines += ["!0", f"{{{n}", f"[1,{n}:0,0:10,10,0", "x2,5:1,1", "]", "!0", f"}}{n}"]
    lines += ["!0", "Postamble:", "Count:1", "!0", "Post scriptum:"]
    write_lines(path, lines)


def test_synctex_merge(tmp_path: Path) -> None:
    a, b = tmp_path / "a.synctex.gz", tmp_path / "b.synctex.gz"
    synctex_file(a, "/build/runs/r1/chapmk-run.tex", 3)
    synctex_file(b, "/build/runs/r2/chapmk-run.tex", 2)
    out = tmp_path / "m.synctex.gz"
    merge(
        [(a, 0), (b, 1), (a, 2)],
        lambda p: "/src/./main.tex" if p.endswith("chapmk-run.tex") else p,
        out,
    )
    m = parse(out)
    assert m.inputs == {"1": "/src/./main.tex", "2": "/tex/a.sty"}
    assert sorted(m.sheets) == [1, 2, 3]
    assert m.sheets[2][0] == "[1,2:0,0:10,10,0" and m.sheets[3][1] == "x2,5:1,1"
    assert m.header["Magnification"] == "1000"
    synctex_file(b, "/x", 1)
    with pytest.raises(SyncTexError, match="no sheet"):
        merge([(b, 4)], str, out)


def test_synctex_merge_renumbers_tags(tmp_path: Path) -> None:
    """Tags renumbered in the order of first use over the merged pages; inputs, offsets and
    empty lines inside sheets dropped; tag 0 kept; Count = record lines without closers."""
    a, b = tmp_path / "a.synctex.gz", tmp_path / "b.synctex.gz"
    head = ["SyncTeX Version:1", "Output:pdf", "Content:"]
    write_lines(a, [
        *head[:1], "Input:1:/r1/chapmk-run.tex", "Input:2:/tex/a.sty", *head[1:],
        "!0", "{1", "[1,3:0,0:1,1,0", "Input:3:/r1/./ch/a.tex", "", "!7", "h3,2:1,1:1,1,0",
        "x0,0:1,1", "]", "!0", "}1", "!0", "Postamble:", "Count:4", "!0", "Post scriptum:",
    ])  # fmt: skip
    write_lines(b, [
        *head[:1], "Input:1:/r2/chapmk-run.tex", "Input:2:/r2/./ch/b.tex", *head[1:],
        "!0", "{1", "!0", "}1", "!0", "{2", "(2,4:0,0:1,1,0", "k1,5:2,2:3", ")", "!0", "}2",
        "!0", "Postamble:", "Count:2", "!0", "Post scriptum:",
    ])  # fmt: skip
    out = tmp_path / "m.synctex.gz"
    merge([(b, 1), (a, 0)], lambda p: p.replace("/r2/", "/r1/"), out)
    lines = read_lines(out)
    assert [x for x in lines if not x.startswith("!")] == [
        "SyncTeX Version:1",
        "Input:1:/r1/./ch/b.tex",
        "Input:2:/r1/chapmk-run.tex",
        "Input:3:/r1/./ch/a.tex",
        "Output:pdf",
        "Content:",
        "{1", "(1,4:0,0:1,1,0", "k2,5:2,2:3", ")", "}1",
        "{2", "[2,3:0,0:1,1,0", "h3,2:1,1:1,1,0", "x0,0:1,1", "]", "}2",
        "Postamble:",
        "Count:5",
        "Post scriptum:",
    ]  # fmt: skip
    assert serialise(lines) == gzip.decompress(out.read_bytes())  # offsets consistent
