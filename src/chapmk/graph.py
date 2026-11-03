"""``chapmk graph`` (PLAN §6.15, S7): compilation units and their dependencies, from the
canonical state of the last build."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from chapmk.analysis import Analysis
from chapmk.canon import read_canon
from chapmk.config import Config
from chapmk.deps import defined_labels
from chapmk.layout import Layout
from chapmk.lint import lint_files
from chapmk.state import load_state

GLUE = "glue"
BIBLIOGRAPHY = "bibliography"


@dataclass
class IncludeNode:
    """One ``\\include`` with what the last build recorded about it."""

    arg: str
    segment: str
    unit: int  # index of its compilation unit (1-based)
    files: list[str]
    imports: dict[str, list[str]]  # exporter (include arg, "glue", "bibliography") -> keys
    lint: list[str]  # lint messages; non-empty = global unit
    pending: list[str]  # dirty reasons if the last build did not converge


@dataclass
class Graph:
    """Compilation units (lists of include args) and include nodes in document order."""

    units: list[list[str]] = field(default_factory=list)
    includes: list[IncludeNode] = field(default_factory=list)


def dependency_graph(analysis: Analysis, layout: Layout, config: Config | None = None) -> Graph:
    """The graph of the last build; raises ``FileNotFoundError`` without a build state."""
    cfg = config or Config()
    lint = (cfg.lint_allow, cfg.lint_verbatim, cfg.lint_shortverb)
    state = load_state(layout.canon_dir)
    if state is None:
        raise FileNotFoundError("no build state: run 'chapmk build' first")
    view = read_canon(analysis, layout.canon_dir)
    owner = dict.fromkeys(defined_labels(view.main), GLUE)
    for k, inc in enumerate(analysis.includes, start=1):
        owner.update(dict.fromkeys(defined_labels(view.unit_aux.get(f"U{k}", [])), inc.arg))
    unit_of = {
        inc.arg: n for n, unit in enumerate(analysis.units, start=1) for inc in unit.includes
    }
    g = Graph(units=[[inc.arg for inc in unit.includes] for unit in analysis.units])
    for k, inc in enumerate(analysis.includes, start=1):
        seg = f"U{k}"
        info = state.units.get(seg)
        imports: dict[str, list[str]] = {}
        for key in sorted(info.imports if info else {}):
            src = BIBLIOGRAPHY if key.startswith("C:") else owner.get(key, "undefined")
            if src != inc.arg:
                imports.setdefault(src, []).append(key[2:])
        files = sorted(state.segment_files.get(seg, {}))
        g.includes.append(
            IncludeNode(
                inc.arg,
                seg,
                unit_of[inc.arg],
                files,
                imports,
                [h.message() for h in lint_files(analysis.source_dir, files, *lint)],
                state.pending.get(seg, []),
            )
        )
    return g


def to_json(g: Graph) -> str:
    return json.dumps(asdict(g), indent=1)


def to_text(g: Graph) -> str:
    lines = []
    by_unit: dict[int, list[IncludeNode]] = {}
    for node in g.includes:
        by_unit.setdefault(node.unit, []).append(node)
    for n, nodes in sorted(by_unit.items()):
        flag = " [global]" if any(node.lint for node in nodes) else ""
        lines.append(f"unit {n}: {', '.join(node.arg for node in nodes)}{flag}")
        for node in nodes:
            lines.append(f"  {node.arg}")
            lines.append(f"    files: {', '.join(node.files) or '-'}")
            for src, keys in sorted(node.imports.items()):
                lines.append(f"    imports from {src}: {', '.join(keys)}")
            for msg in node.lint:
                lines.append(f"    lint: {msg}")
            if node.pending:
                lines.append(f"    dirty: {'; '.join(node.pending)}")
    return "\n".join(lines) + "\n"


def to_dot(g: Graph) -> str:
    """Graphviz: clusters = compilation units; solid edges = imports (exporter -> importer),
    dashed edges = entry state (document order)."""

    def q(name: str) -> str:
        return '"' + name.replace('"', '\\"') + '"'

    out = ["digraph chapmk {", "  rankdir=LR;", "  node [shape=box];"]
    by_unit: dict[int, list[IncludeNode]] = {}
    for node in g.includes:
        by_unit.setdefault(node.unit, []).append(node)
    for n, nodes in sorted(by_unit.items()):
        out.append(f"  subgraph cluster_{n} {{ label={q(f'unit {n}')};")
        for node in nodes:
            style = ", style=bold, color=red" if node.lint else ""
            out.append(f"    {q(node.arg)} [label={q(node.arg)}{style}];")
        out.append("  }")
    for a, b in zip(g.includes, g.includes[1:], strict=False):
        out.append(f"  {q(a.arg)} -> {q(b.arg)} [style=dashed];")
    for node in g.includes:
        for src, keys in sorted(node.imports.items()):
            out.append(f"  {q(src)} -> {q(node.arg)} [label={q(str(len(keys)))}];")
    out.append("}")
    return "\n".join(out) + "\n"
