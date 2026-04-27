#!/usr/bin/env python3
"""MCPRated render_badges — generate SVG badges from lint data.

Outputs (to build/site/badges/v1/):
  <owner>__<repo>.svg              — compact composite (e.g. "MCPRated · 92/100")
  <owner>__<repo>_reliability.svg  — per-axis
  <owner>__<repo>_documentation.svg
  <owner>__<repo>_trust.svg
  <owner>__<repo>_community.svg

Versioned URL path (`/badges/v1/...`) so embedded badges keep style/algorithm
even when ruleset bumps to v2.

Pure stdlib. SVG hand-built (~100 LOC). Shields.io-style metrics: 20px high.
"""
from __future__ import annotations
import argparse, html, json, sys
from pathlib import Path

# Color thresholds (matches landing page CSS)
GOOD = "#3fb950"    # green
OK = "#d29922"      # yellow
WEAK = "#f85149"    # red
NEUTRAL = "#555"    # left-side label background


def color_for(score: int) -> str:
    if score >= 90:
        return GOOD
    if score >= 50:
        return OK
    return WEAK


# Approximate text width in pixels for Verdana 11px (used by Shields.io style)
# Quick lookup table; doesn't need to be perfect, just close enough for layout
_CHAR_WIDTHS = {
    " ": 4, "0": 7, "1": 7, "2": 7, "3": 7, "4": 7, "5": 7, "6": 7, "7": 7, "8": 7, "9": 7,
    "/": 4, "·": 4, ".": 3, "-": 4, "_": 7,
}
def _txt_width(s: str) -> int:
    """Estimate pixel width of label text in 11px Verdana."""
    w = 0
    for ch in s:
        if ch in _CHAR_WIDTHS:
            w += _CHAR_WIDTHS[ch]
        elif ch.isupper():
            w += 8
        elif ch.islower():
            w += 7
        else:
            w += 7
    return w


def _badge(label: str, value: str, value_color: str) -> str:
    """Build a Shields.io-style 20px tall SVG badge."""
    # Padding: 5px on each side of each text region
    label_pad = 6
    value_pad = 6
    label_w = _txt_width(label) + label_pad * 2
    value_w = _txt_width(value) + value_pad * 2
    total_w = label_w + value_w
    label_x = label_w / 2
    value_x = label_w + value_w / 2

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20" role="img" aria-label="{html.escape(label)}: {html.escape(value)}">
  <title>{html.escape(label)}: {html.escape(value)}</title>
  <linearGradient id="g" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_w}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_w}" height="20" fill="{NEUTRAL}"/>
    <rect x="{label_w}" width="{value_w}" height="20" fill="{value_color}"/>
    <rect width="{total_w}" height="20" fill="url(#g)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="{label_x}" y="15" fill="#010101" fill-opacity=".3">{html.escape(label)}</text>
    <text x="{label_x}" y="14">{html.escape(label)}</text>
    <text x="{value_x}" y="15" fill="#010101" fill-opacity=".3">{html.escape(value)}</text>
    <text x="{value_x}" y="14">{html.escape(value)}</text>
  </g>
</svg>
'''


def composite_badge(score: int, hard_flags: list) -> str:
    # Hard flag override displays in place of score
    if "archived" in hard_flags or "disabled" in hard_flags:
        return _badge("MCPRated", "archived", WEAK)
    return _badge("MCPRated", f"{score}/100", color_for(score))


def axis_badge(axis_name: str, score: int) -> str:
    label = axis_name.capitalize()
    return _badge(f"MCPRated {label}", f"{score}/100", color_for(score))


def render_for_server(server: dict) -> dict[str, str]:
    """Return {filename_suffix: svg_text} for one server."""
    out = {}
    flags = server.get("hard_flags", [])
    if isinstance(flags, list) and flags and isinstance(flags[0], dict):
        flag_keys = [f.get("key") for f in flags]
    else:
        flag_keys = flags or []
    out[""] = composite_badge(server["composite"], flag_keys)
    axes = server.get("axes", {})
    if isinstance(axes, dict):
        for axis_name in ("reliability", "documentation", "trust", "community"):
            ax_data = axes.get(axis_name, {})
            score = ax_data["score"] if isinstance(ax_data, dict) else ax_data
            if isinstance(score, int):
                out[f"_{axis_name}"] = axis_badge(axis_name, score)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="dir containing index.json + servers/")
    ap.add_argument("--out", default="build/site/badges/v1", help="output dir")
    args = ap.parse_args()

    data_dir = Path(args.data)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    idx_path = data_dir / "index.json"
    if not idx_path.exists():
        print(f"ERROR: {idx_path} not found", file=sys.stderr)
        return 1

    idx = json.loads(idx_path.read_text())
    servers = idx.get("servers", [])

    # For composite + axes we need per-server data (full lint detail), not just index summary
    servers_dir = data_dir / "servers"
    count = 0
    for s in servers:
        slug = s.get("slug") or s["repo"].replace("/", "__")
        full_path = servers_dir / f"{slug}.json"
        if full_path.exists():
            full = json.loads(full_path.read_text())
            # Ensure composite and axes available — index.json has axes but we want consistent shape
            full_data = {
                "composite": full["composite"],
                "axes": full["axes"],
                "hard_flags": full.get("hard_flags", []),
            }
        else:
            # Fallback: derive from index entry (axes are flat ints there)
            full_data = {
                "composite": s["composite"],
                "axes": {a: {"score": v} for a, v in s["axes"].items()},
                "hard_flags": s.get("hard_flags", []),
            }
        for suffix, svg in render_for_server(full_data).items():
            (out_dir / f"{slug}{suffix}.svg").write_text(svg)
            count += 1

    print(f"Rendered {count} SVG badges to {out_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
