"""Tests for individual lint signal functions and the prefilter.

Each signal: at least one passing case + at least one failing case.
Some signals have nuanced edge cases (e.g. workspace mono-repo handling
in s_no_floating_sdk) — those get extra coverage.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import json
import pytest

import lint


# ---------------------------------------------------------------------------
# Reliability axis (7 signals)
# ---------------------------------------------------------------------------

class TestReliability:
    def test_has_ci_pass(self, make_repo):
        d = make_repo(has_ci=True)
        ok, _ = lint.s_has_ci(d)
        assert ok

    def test_has_ci_fail(self, make_repo):
        d = make_repo(has_ci=False)
        ok, reason = lint.s_has_ci(d)
        assert not ok
        assert "workflows" in reason

    def test_no_floating_sdk_no_pkg(self, make_repo):
        # No pkg metadata means we can't observe — counts as N/A pass.
        d = make_repo(pkg={})
        ok, _ = lint.s_no_floating_sdk(d)
        assert ok

    def test_no_floating_sdk_pinned_dep(self, make_repo):
        d = make_repo(pkg={
            "package.json": '{"dependencies":{"@modelcontextprotocol/sdk":"^1.2.3"}}',
        })
        ok, _ = lint.s_no_floating_sdk(d)
        assert ok

    def test_no_floating_sdk_floating_latest(self, make_repo):
        d = make_repo(pkg={
            "package.json": '{"dependencies":{"@modelcontextprotocol/sdk":"latest"}}',
        })
        ok, reason = lint.s_no_floating_sdk(d)
        assert not ok
        assert "floating" in reason.lower()

    def test_no_floating_sdk_workspace_internal(self, make_repo):
        # Mono-repo workspaces use "*" for internal deps; should pass.
        d = make_repo(pkg={
            "package.json": '{"workspaces":["packages/*"],"dependencies":{"@modelcontextprotocol/sdk":"*"}}',
        })
        ok, _ = lint.s_no_floating_sdk(d)
        assert ok

    def test_recently_maintained_recent(self, make_repo):
        recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace("+00:00", "Z")
        d = make_repo(pushed_at=recent)
        ok, _ = lint.s_recently_maintained(d)
        assert ok

    def test_recently_maintained_stale(self, make_repo):
        stale = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat().replace("+00:00", "Z")
        d = make_repo(pushed_at=stale)
        ok, _ = lint.s_recently_maintained(d)
        assert not ok

    def test_has_releases_pass(self, make_repo):
        d = make_repo(releases_count=3)
        ok, _ = lint.s_has_releases(d)
        assert ok

    def test_has_releases_fail(self, make_repo):
        d = make_repo(releases_count=0)
        ok, _ = lint.s_has_releases(d)
        assert not ok


# ---------------------------------------------------------------------------
# Documentation axis (5 signals)
# ---------------------------------------------------------------------------

class TestDocumentation:
    def test_readme_substantive_long_enough(self, make_repo):
        d = make_repo(readme="# My MCP Server\n\n" + "Lorem ipsum.\n" * 80)
        ok, _ = lint.s_readme_substantive(d)
        assert ok

    def test_readme_substantive_too_short(self, make_repo):
        d = make_repo(readme="# Short\n\nNot much here.")
        ok, _ = lint.s_readme_substantive(d)
        assert not ok

    def test_install_instructions_npx(self, make_repo):
        d = make_repo(readme="```bash\nnpx -y @scope/pkg\n```")
        ok, _ = lint.s_install_instructions(d)
        assert ok

    def test_install_instructions_uvx(self, make_repo):
        d = make_repo(readme="```bash\nuvx my-server\n```")
        ok, _ = lint.s_install_instructions(d)
        assert ok

    def test_install_instructions_missing(self, make_repo):
        d = make_repo(readme="A server. Use it. Goodbye.")
        ok, _ = lint.s_install_instructions(d)
        assert not ok


# ---------------------------------------------------------------------------
# Trust axis (3 signals)
# ---------------------------------------------------------------------------

class TestTrust:
    @pytest.mark.parametrize("spdx", ["MIT", "Apache-2.0", "BSD-3-Clause", "MPL-2.0", "ISC"])
    def test_license_commercial_pass(self, make_repo, spdx):
        d = make_repo(license_spdx=spdx)
        ok, _ = lint.s_license_commercial(d)
        assert ok, f"expected {spdx} to pass commercial check"

    @pytest.mark.parametrize("spdx", ["GPL-3.0", "AGPL-3.0", None])
    def test_license_commercial_fail(self, make_repo, spdx):
        d = make_repo(license_spdx=spdx)
        ok, _ = lint.s_license_commercial(d)
        assert not ok

    def test_has_security_policy_pass(self, make_repo):
        d = make_repo(top_paths=["README.md", "SECURITY.md"])
        ok, _ = lint.s_has_security_policy(d)
        assert ok

    def test_has_security_policy_fail(self, make_repo):
        d = make_repo(top_paths=["README.md"])
        ok, _ = lint.s_has_security_policy(d)
        assert not ok

    def test_has_repo_topics_pass(self, make_repo):
        d = make_repo(topics=["mcp", "database"])
        ok, _ = lint.s_has_repo_topics(d)
        assert ok

    def test_has_repo_topics_fail_empty(self, make_repo):
        d = make_repo(topics=[])
        ok, _ = lint.s_has_repo_topics(d)
        assert not ok


# ---------------------------------------------------------------------------
# Community axis (5 signals)
# ---------------------------------------------------------------------------

class TestCommunity:
    def test_has_contributing_pass(self, make_repo):
        d = make_repo(top_paths=["CONTRIBUTING.md"])
        ok, _ = lint.s_has_contributing(d)
        assert ok

    def test_has_contributing_fail(self, make_repo):
        d = make_repo(top_paths=["README.md"])
        ok, _ = lint.s_has_contributing(d)
        assert not ok

    def test_multiple_contributors_pass(self, make_repo):
        d = make_repo(commits_90d=[
            {"sha": "1", "author": {"login": "alice"}, "commit": {"author": {"date": "2026-04-01T00:00:00Z"}}},
            {"sha": "2", "author": {"login": "bob"}, "commit": {"author": {"date": "2026-04-02T00:00:00Z"}}},
        ])
        ok, _ = lint.s_multiple_contributors(d)
        assert ok

    def test_multiple_contributors_solo(self, make_repo):
        d = make_repo(commits_90d=[
            {"sha": "1", "author": {"login": "alice"}, "commit": {"author": {"date": "2026-04-01T00:00:00Z"}}},
        ])
        ok, _ = lint.s_multiple_contributors(d)
        assert not ok


# ---------------------------------------------------------------------------
# Prefilter — is_mcp_server gating on lint pipeline entry
# ---------------------------------------------------------------------------

class TestPrefilter:
    def test_passes_with_sdk_dep(self, make_repo):
        d = make_repo(pkg={"package.json": '{"dependencies":{"@modelcontextprotocol/sdk":"1"}}'})
        is_mcp, _ = lint.is_mcp_server(d)
        assert is_mcp

    def test_passes_with_python_pep621(self, make_repo):
        d = make_repo(pkg={
            "pyproject.toml": '[project]\ndependencies = [\n  "mcp==1.27.0",\n]\n',
        })
        is_mcp, _ = lint.is_mcp_server(d)
        assert is_mcp

    def test_passes_with_run_pattern_in_source(self, make_repo):
        d = make_repo(
            description="not obvious",
            source_files={"main.go": 'import "github.com/mark3labs/mcp-go"\n'},
            pkg={},
        )
        is_mcp, _ = lint.is_mcp_server(d)
        assert is_mcp

    def test_passes_with_mcp_servers_config(self, make_repo):
        d = make_repo(readme='Add to config: ```json\n{"mcpServers": {}}```', pkg={})
        is_mcp, _ = lint.is_mcp_server(d)
        assert is_mcp

    def test_passes_with_mcp_in_description(self, make_repo):
        d = make_repo(description="An MCP server for X", pkg={})
        is_mcp, _ = lint.is_mcp_server(d)
        assert is_mcp

    def test_passes_with_name_pattern(self, make_repo):
        d = make_repo(name="x-mcp-server", description="X", pkg={})
        is_mcp, _ = lint.is_mcp_server(d)
        assert is_mcp

    def test_rejects_unrelated_repo(self, make_repo):
        d = make_repo(name="random-app", description="Just an app", pkg={})
        is_mcp, _ = lint.is_mcp_server(d)
        assert not is_mcp


# ---------------------------------------------------------------------------
# Full lint integration — produces required keys + reasonable composite
# ---------------------------------------------------------------------------

class TestLintIntegration:
    def test_lint_output_has_required_keys(self, repo_server_typescript_sdk):
        result = lint.lint(repo_server_typescript_sdk)
        for key in ("repo", "composite", "axes", "kind", "subkind",
                    "capabilities", "rule_set_version", "scored_at",
                    "hard_flags", "distribution"):
            assert key in result, f"lint output missing {key}"

    def test_lint_axes_have_score(self, repo_server_typescript_sdk):
        result = lint.lint(repo_server_typescript_sdk)
        for axis in ("reliability", "documentation", "trust", "community"):
            assert axis in result["axes"]
            assert "score" in result["axes"][axis]
            assert 0 <= result["axes"][axis]["score"] <= 100

    def test_lint_composite_in_range(self, repo_server_typescript_sdk):
        result = lint.lint(repo_server_typescript_sdk)
        assert 0 <= result["composite"] <= 100
