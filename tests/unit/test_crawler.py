"""Tests for crawler.py — currently focused on _candidate_source_paths,
the helper that decides which source files to fetch.

We don't make HTTP — we test pure helpers and structural decisions.
"""
from __future__ import annotations
import pytest

import crawler


class TestCandidateSourcePaths:
    """Crawler should propose enough candidate paths that extractor sees
    typical SDK file layouts (src/index.ts, server.py, src/tools/*).

    Failing tests pin gaps that motivated the v1.1 expansion."""

    def test_includes_classic_entry_points(self):
        paths = crawler._candidate_source_paths("example-mcp")
        # The basics we already had
        for p in ["index.ts", "src/index.ts", "main.py", "server.py", "main.go"]:
            assert p in paths, f"missing classic candidate: {p}"

    def test_includes_tools_subdirectories(self):
        paths = crawler._candidate_source_paths("example-mcp")
        # New: many TS servers split tool defs into src/tools/<thing>.ts
        # Crawler must propose these so the extractor catches them.
        assert any("tools/" in p or p.endswith("/tools") for p in paths), (
            f"no tools/ subdirectory candidates in: {paths}"
        )

    def test_python_package_path_uses_underscores(self):
        # For Python packages, mcp-time → mcp_time (PEP 8 import name).
        paths = crawler._candidate_source_paths("mcp-time")
        assert any("mcp_time" in p for p in paths)

    def test_handles_single_word_name(self):
        # No hyphens, nothing to convert.
        paths = crawler._candidate_source_paths("server")
        assert "server.py" in paths or "main.py" in paths

    def test_capped_to_reasonable_size(self):
        # Crawler should cap proposals; we'll fetch ~10 actual files at most.
        paths = crawler._candidate_source_paths("any-mcp")
        assert len(paths) < 50, f"too many candidate paths: {len(paths)}"
