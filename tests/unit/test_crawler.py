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


class TestSubdirsToExplore:
    """E1: many real servers put source in subdirectories the static
    candidate list doesn't enumerate (microsoft/playwright-mcp has src/,
    github-mcp-server has cmd/ + internal/ + pkg/, awslabs/mcp has src/,
    supabase-mcp has packages/, mcprated has worker/). When the static
    candidates miss, the extractor sees zero source and returns 0 tools.

    _subdirs_to_explore inspects the top-level repo listing and returns
    which standard source-bearing subdirectories are actually present, so
    the crawler can list and fetch from them.
    """

    def test_returns_only_dirs_actually_present(self):
        result = crawler._subdirs_to_explore(["src", "tests", "README.md", "go.mod"])
        assert "src" in result
        assert "tests" not in result  # not a known source dir
        assert "README.md" not in result

    def test_recognizes_go_monorepo_layout(self):
        # github/github-mcp-server has cmd/ + pkg/ + internal/
        top = ["cmd", "internal", "pkg", "go.mod", "README.md"]
        result = crawler._subdirs_to_explore(top)
        for expected in ["cmd", "internal", "pkg"]:
            assert expected in result, f"{expected} should be explored"

    def test_recognizes_typescript_monorepo_layout(self):
        # supabase-community/supabase-mcp has packages/
        top = ["packages", "package.json", "pnpm-workspace.yaml"]
        result = crawler._subdirs_to_explore(top)
        assert "packages" in result

    def test_recognizes_workspace_subdirs(self):
        # mcprated has worker/, awslabs/mcp has src/
        top = ["worker", "linter", "data", "README.md"]
        result = crawler._subdirs_to_explore(top)
        assert "worker" in result

    def test_skips_when_no_known_subdir_present(self):
        # Single-file npm package — playwright-mcp pattern
        top = ["index.js", "cli.js", "package.json", "README.md"]
        result = crawler._subdirs_to_explore(top)
        # No dirs to explore — returns empty
        assert result == [] or all(d not in top for d in result)

    def test_deterministic_ordering(self):
        # Crawler exhausts a fetch budget; ordering must be stable so
        # which dirs win is predictable.
        a = crawler._subdirs_to_explore(["src", "cmd", "packages"])
        b = crawler._subdirs_to_explore(["packages", "cmd", "src"])
        assert a == b


class TestDetectPublishedPackages:
    """Regression: crawler used `re` without importing it. Caught only by
    the smoke harness, missing from unit coverage. Pin the helper now."""

    def test_npm_package_name_extracted(self):
        pj = '{"name": "@scope/foo-bar", "version": "1.0.0"}'
        result = crawler._detect_published_packages({"package.json": pj})
        assert ("npm", "@scope/foo-bar") in result

    def test_pypi_package_name_extracted(self):
        py = '[project]\nname = "my-mcp-server"\nversion = "1.0"\n'
        result = crawler._detect_published_packages({"pyproject.toml": py})
        assert ("PyPI", "my-mcp-server") in result

    def test_cargo_package_name_extracted(self):
        cargo = '[package]\nname = "foo-mcp"\nversion = "0.1"\n'
        result = crawler._detect_published_packages({"Cargo.toml": cargo})
        assert ("crates.io", "foo-mcp") in result

    def test_no_packages_when_metadata_empty(self):
        assert crawler._detect_published_packages({}) == []

    def test_handles_malformed_json_gracefully(self):
        # Degraded input shouldn't crash the crawler.
        assert crawler._detect_published_packages({"package.json": "{not json"}) == []


class TestSemverCompare:
    """Pure helpers for the OSV version-aware filter."""

    @pytest.mark.parametrize("v, expected", [
        ("1.2.3", (1, 2, 3)),
        ("0", (0, 0, 0)),
        ("1", (1, 0, 0)),
        ("1.2", (1, 2, 0)),
        ("1.2.3-rc1", (1, 2, 3)),  # pre-release tag stripped
        ("v1.2.3", (1, 2, 3)),     # leading v tolerated
    ])
    def test_semver_tuple(self, v, expected):
        assert crawler._semver_tuple(v) == expected

    def test_garbage_returns_zero(self):
        assert crawler._semver_tuple("not a version") == (0, 0, 0)


class TestIsVersionAffected:
    """Phase I-2 fix: only flag advisories that actually affect the
    latest published version. Avoid the 'package once had a CVE in v0.x,
    fixed in v1.0' false positive that capped popular SDKs unfairly."""

    def test_simple_introduced_fixed_range_affected(self):
        affected = [{
            "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.5.0"}]}],
        }]
        assert crawler._is_version_affected("1.0.0", affected) is True

    def test_simple_introduced_fixed_range_safe(self):
        affected = [{
            "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.5.0"}]}],
        }]
        assert crawler._is_version_affected("2.0.0", affected) is False
        assert crawler._is_version_affected("1.5.0", affected) is False  # fix is exclusive lower bound for safety

    def test_introduced_after_zero(self):
        # Bug introduced in 1.0, fixed in 1.5
        affected = [{
            "ranges": [{"events": [{"introduced": "1.0.0"}, {"fixed": "1.5.0"}]}],
        }]
        assert crawler._is_version_affected("0.9.0", affected) is False
        assert crawler._is_version_affected("1.2.0", affected) is True
        assert crawler._is_version_affected("1.5.0", affected) is False

    def test_open_ended_range_no_fix(self):
        # Vulnerability disclosed but never fixed — every version >= introduced affected
        affected = [{
            "ranges": [{"events": [{"introduced": "0"}]}],
        }]
        assert crawler._is_version_affected("1.0.0", affected) is True
        assert crawler._is_version_affected("99.0.0", affected) is True

    def test_explicit_versions_list_match(self):
        affected = [{
            "versions": ["1.0.0", "1.0.1", "1.0.2"],
        }]
        assert crawler._is_version_affected("1.0.1", affected) is True
        assert crawler._is_version_affected("1.0.3", affected) is False

    def test_multiple_ranges_branches(self):
        # 0.x and 1.x both had the bug; both fixed in their own branches.
        affected = [{
            "ranges": [
                {"events": [{"introduced": "0"}, {"fixed": "0.5.0"}]},
                {"events": [{"introduced": "1.0.0"}, {"fixed": "1.2.0"}]},
            ],
        }]
        assert crawler._is_version_affected("0.3.0", affected) is True
        assert crawler._is_version_affected("0.7.0", affected) is False
        assert crawler._is_version_affected("1.1.0", affected) is True
        assert crawler._is_version_affected("1.5.0", affected) is False

    def test_no_data_returns_true_conservatively(self):
        # If we can't decide, fall back to "treat as affected" — better to
        # over-flag than silently mark vulnerable repo as safe.
        assert crawler._is_version_affected("1.0.0", []) is True
        assert crawler._is_version_affected("1.0.0", [{}]) is True
        # Also when version itself is missing/garbage
        assert crawler._is_version_affected("", [{"ranges": [{"events": [{"fixed": "1.0"}]}]}]) is True
