"""Tests for render_pages — landing HTML + llms.txt.

Primary purpose: regression-test the f-string formatting. We had a crash
in deploy-pages CI when literal `{...}` JSON examples were added to a
template f-string without `{{...}}` escaping. These tests catch that class
of bug locally before push.
"""
from __future__ import annotations
import pytest

import render_pages


def _minimal_index():
    """Smallest index.json shape that render_pages accepts without crashing."""
    return {
        "rule_set_version": "1.1.0",
        "taxonomy_version": "1.0",
        "generated_at": "2026-04-28T00:00:00+00:00",
        "count": 1,
        "servers": [{
            "repo": "x/y",
            "slug": "x__y",
            "composite": 80,
            "axes": {"reliability": 80, "documentation": 80, "trust": 80, "community": 80},
            "stars": 100,
            "language": "TypeScript",
            "kind": "server",
            "subkind": "integration",
            "capabilities": ["devtools"],
            "hard_flags": [],
        }],
    }


class TestRenderIndex:
    def test_does_not_crash_on_minimal_input(self):
        # Regression: would crash if any f-string template contains literal
        # `{...}` JSON examples that weren't escaped to `{{...}}`.
        html = render_pages.render_index(_minimal_index(), "mcprated/mcprated")
        assert isinstance(html, str)
        assert len(html) > 1000  # rough sanity — should be a real HTML doc

    def test_includes_install_command(self):
        # Phase B: install command must surface in the hero block so a
        # cold visitor sees the URL on first paint.
        html = render_pages.render_index(_minimal_index(), "mcprated/mcprated")
        assert "claude mcp add" in html
        assert "mcp.mcprated.workers.dev" in html

    def test_html_well_formed_basics(self):
        html = render_pages.render_index(_minimal_index(), "mcprated/mcprated")
        # Minimal sanity: matched <html>, <body>, doctype
        assert html.lstrip().lower().startswith("<!doctype html>")
        assert "</html>" in html


class TestRenderLlmsTxt:
    def test_does_not_crash(self):
        out = render_pages.render_llms_txt(_minimal_index(), "mcprated/mcprated")
        assert isinstance(out, str)

    def test_includes_mcp_endpoint(self):
        # Phase B: an agent fetching /llms.txt for discovery should learn
        # about the live MCP endpoint at the top.
        out = render_pages.render_llms_txt(_minimal_index(), "mcprated/mcprated")
        assert "mcp.mcprated.workers.dev" in out
        assert "claude mcp add" in out
