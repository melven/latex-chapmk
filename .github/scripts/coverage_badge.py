"""Write a coverage badge (SVG, shields.io look) for the README: coverage_badge.py PERCENT OUT.

No external service: CI publishes the file on the branch ``badges``; the README links it to
the CI runs on main, whose summaries hold the per-module table.
"""

import sys
from pathlib import Path


def color(percent: float) -> str:
    for limit, value in ((95, "#4c1"), (90, "#97ca00"), (80, "#a4a61d"), (70, "#dfb317")):
        if percent >= limit:
            return value
    return "#e05d44"


def badge(percent: float) -> str:
    label, value = "coverage", f"{percent:.0f}%"
    lw, vw = 61, 8 * len(value) + 10  # widths for Verdana 11 (as shields.io)
    w = lw + vw
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" '
        f'aria-label="{label}: {value}"><title>{label}: {value}</title>'
        f'<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" '
        f'stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)"><rect width="{lw}" height="20" fill="#555"/>'
        f'<rect x="{lw}" width="{vw}" height="20" fill="{color(percent)}"/>'
        f'<rect width="{w}" height="20" fill="url(#s)"/></g>'
        f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,'
        f'sans-serif" font-size="11"><text x="{lw / 2}" y="14">{label}</text>'
        f'<text x="{lw + vw / 2}" y="14">{value}</text></g></svg>\n'
    )


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(badge(float(sys.argv[1])), encoding="utf-8")
