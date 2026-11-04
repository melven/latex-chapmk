"""Unit tests for graph.py (chapmk graph)."""

from pathlib import Path

import pytest


def test_graph_renderers() -> None:
    from chapmk.graph import Graph, IncludeNode, to_dot, to_json, to_text

    g = Graph(
        units=[["a"], ["b", "b2"]],
        includes=[
            IncludeNode("a", "U1", 1, ["a.tex"], {"b": ["sec:x"], "bibliography": ["k"]}, [], []),
            IncludeNode("b", "U2", 2, ["b.tex"], {}, ["b.tex:3: \\setlength ..."], ["x"]),
            IncludeNode("b2", "U3", 2, [], {}, [], []),
        ],
    )
    text = to_text(g)
    assert "unit 2: b, b2 [global]" in text and "imports from b: sec:x" in text
    assert "dirty: x" in text and "files: -" in text
    dot = to_dot(g)
    assert '"b" -> "a" [label="1"];' in dot and '"a" -> "b" [style=dashed];' in dot
    assert "cluster_2" in dot and "color=red" in dot
    assert '"units"' in to_json(g)


def test_graph_without_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from chapmk.cli import main

    (tmp_path / "d.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert main(["graph", "d.tex"], cwd=tmp_path) == 2
    assert "run 'chapmk build' first" in capsys.readouterr().err
