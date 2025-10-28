#!/usr/bin/env python3
"""
Generate an SVG coverage badge from pytest-cov JSON output.
Usage:
    python scripts/generate_badge.py coverage.json badges/coverage.svg
"""

import sys
from pathlib import Path


def coverage_to_color(coverage: float) -> str:
    """Return a badge color for the given coverage percentage."""
    if coverage >= 80:
        return "green"
    elif coverage >= 65:
        return "orange"
    elif coverage >= 50:
        return "yellow"
    else:
        return "red"


def generate_badge(coverage: float, color: str) -> str:
    """Return SVG badge content as a string."""
    label = "coverage"
    color_map = {
        "yellow": "#FFFF00",
        "red": "#FF0000",
        "orange": "#FF8000",
        "green": "#008000",
    }
    value = f"{int(round(coverage))}%"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="120" height="20">
  <linearGradient id="a" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <rect rx="3" width="120" height="20" fill="#555"/>
  <rect rx="3" x="60" width="60" height="20" fill="{color_map[color]}"/>
  <path fill="{color_map[color]}" d="M60 0h4v20h-4z"/>
  <rect rx="3" width="120" height="20" fill="url(#a)"/>
  <g fill="#fff" text-anchor="middle" font-family="Verdana" font-size="11">
    <text x="30" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="30" y="14">{label}</text>
    <text x="90" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="90" y="14">{value}</text>
  </g>
</svg>"""


def main(coverage_score: str, output_path: str) -> None:
    coverage_score = float(coverage_score)
    out_file = Path(output_path)
    color = coverage_to_color(coverage_score)
    svg = generate_badge(coverage_score, color)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(svg)
    print(f"Generated {out_file} ({coverage_score:.1f}% coverage, color: {color})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python generate_badge.py coverage.json badges/coverage.svg")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
