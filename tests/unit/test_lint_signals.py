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

    # G5: has_repo_topics retired in rule_set v1.2 (cosmetic, not a real
    # trust signal per cross-LLM review). Replaced by org_owned + has_codeowners.

    def test_org_owned_pass(self, make_repo):
        d = make_repo(owner="microsoft")
        d["repo"]["owner"]["type"] = "Organization"
        ok, _ = lint.s_org_owned(d)
        assert ok

    def test_org_owned_fail_user_account(self, make_repo):
        d = make_repo(owner="some-dev")
        d["repo"]["owner"]["type"] = "User"
        ok, _ = lint.s_org_owned(d)
        assert not ok

    def test_org_owned_handles_missing_type(self, make_repo):
        # Some old crawler caches don't include owner.type — treat as User
        # (conservative: don't credit ambiguous repos).
        d = make_repo()
        # owner.type not set
        ok, _ = lint.s_org_owned(d)
        assert not ok

    def test_has_codeowners_root(self, make_repo):
        d = make_repo(top_paths=["README.md", "CODEOWNERS"])
        ok, _ = lint.s_has_codeowners(d)
        assert ok

    def test_has_codeowners_in_dotgithub(self, make_repo):
        d = make_repo(top_paths=["README.md", ".github"])
        # CODEOWNERS at .github/CODEOWNERS — crawler doesn't fetch nested,
        # but we can recognize a .github dir with the codeowners convention
        # ONLY when explicitly listed as ".github/CODEOWNERS" in top_paths.
        # Here we assume it ISN'T fetched; should fail.
        ok, _ = lint.s_has_codeowners(d)
        assert not ok

    def test_has_codeowners_explicit_dotgithub_path(self, make_repo):
        d = make_repo(top_paths=["README.md", ".github/CODEOWNERS"])
        ok, _ = lint.s_has_codeowners(d)
        assert ok

    def test_has_codeowners_fail(self, make_repo):
        d = make_repo(top_paths=["README.md", "LICENSE"])
        ok, _ = lint.s_has_codeowners(d)
        assert not ok


class TestScorecardSignals:
    """Phase I-1: OpenSSF Scorecard signals — strongest deterministic Trust
    expansion possible without runtime probing or auth-required APIs.

    Each signal reads d['scorecard']['checks'] which is a list populated by
    crawler.fetch_repo from https://api.securityscorecards.dev. When Scorecard
    has not analyzed the repo, signals fail-closed (don't credit the absence).
    """

    def _scorecard(self, **scores):
        # Helper: build a scorecard dict matching the public API shape.
        return {"score": 5, "checks": [
            {"name": name, "score": score} for name, score in scores.items()
        ]}

    def test_signed_releases_pass(self, make_repo):
        d = make_repo()
        d["scorecard"] = self._scorecard(**{"Signed-Releases": 7})
        ok, _ = lint.s_signed_releases(d)
        assert ok

    def test_signed_releases_fail_low_score(self, make_repo):
        d = make_repo()
        d["scorecard"] = self._scorecard(**{"Signed-Releases": 2})
        ok, _ = lint.s_signed_releases(d)
        assert not ok

    def test_signed_releases_fail_no_scorecard(self, make_repo):
        # Conservative: missing data → don't credit the repo.
        d = make_repo()  # no scorecard key
        ok, _ = lint.s_signed_releases(d)
        assert not ok

    def test_pinned_dependencies_pass(self, make_repo):
        d = make_repo()
        d["scorecard"] = self._scorecard(**{"Pinned-Dependencies": 8})
        ok, _ = lint.s_pinned_dependencies(d)
        assert ok

    def test_branch_protection_pass(self, make_repo):
        d = make_repo()
        d["scorecard"] = self._scorecard(**{"Branch-Protection": 6})
        ok, _ = lint.s_branch_protection(d)
        assert ok

    def test_branch_protection_fail_threshold(self, make_repo):
        d = make_repo()
        d["scorecard"] = self._scorecard(**{"Branch-Protection": 4})
        ok, _ = lint.s_branch_protection(d)
        assert not ok

    def test_token_permissions_pass(self, make_repo):
        d = make_repo()
        d["scorecard"] = self._scorecard(**{"Token-Permissions": 8})
        ok, _ = lint.s_token_permissions(d)
        assert ok

    def test_dependency_update_tool_pass(self, make_repo):
        # Score 10 = Dependabot or Renovate active
        d = make_repo()
        d["scorecard"] = self._scorecard(**{"Dependency-Update-Tool": 10})
        ok, _ = lint.s_dependency_update_tool(d)
        assert ok

    def test_no_dangerous_workflow_pass(self, make_repo):
        d = make_repo()
        d["scorecard"] = self._scorecard(**{"Dangerous-Workflow": 10})
        ok, _ = lint.s_no_dangerous_workflow(d)
        assert ok

    def test_no_dangerous_workflow_fail_low(self, make_repo):
        d = make_repo()
        d["scorecard"] = self._scorecard(**{"Dangerous-Workflow": 5})
        ok, _ = lint.s_no_dangerous_workflow(d)
        assert not ok


class TestOSVHardFlag:
    """Phase I-2: any HIGH/CRITICAL open advisory across the server's
    declared packages caps composite at 50."""

    def test_critical_cve_triggers_flag(self, make_repo):
        d = make_repo()
        d["osv_advisories"] = [
            {"id": "GHSA-xxx", "severity": "CRITICAL",
             "package": "lodash", "ecosystem": "npm"}
        ]
        flag = lint._has_critical_cve_flag(d)
        assert flag is not None
        key, msg = flag
        assert key == "has_critical_cve"

    def test_high_cve_triggers_flag(self, make_repo):
        d = make_repo()
        d["osv_advisories"] = [
            {"id": "CVE-2024-x", "severity": "HIGH"}
        ]
        flag = lint._has_critical_cve_flag(d)
        assert flag is not None

    def test_low_cve_does_not_trigger(self, make_repo):
        d = make_repo()
        d["osv_advisories"] = [
            {"id": "GHSA-yyy", "severity": "LOW"}
        ]
        flag = lint._has_critical_cve_flag(d)
        assert flag is None

    def test_no_advisories_no_flag(self, make_repo):
        d = make_repo()  # no osv_advisories key
        flag = lint._has_critical_cve_flag(d)
        assert flag is None


class TestRegistrySignals:
    """Phase M: free signals from npm + PyPI registries (no auth required).

    Registry data is fetched by crawler into cache_entry["registry"]:
        {
          "ecosystem": "npm" | "PyPI" | "crates.io",
          "package": "...",
          "weekly_downloads": int | None,
          "latest_published_at": ISO8601 | None,
          "deprecated": bool,
          "exists": bool,
        }

    Signal mapping (cross-axis):
      Reliability:
        - published_to_registry  — exists == True
        - recent_publish         — latest_published_at within 365d
        - not_deprecated         — deprecated != True
      Trust:
        - weekly_downloads_meaningful — >= 10 downloads/week
    """

    def _registry(self, **fields):
        base = {"ecosystem": "npm", "package": "x", "exists": True,
                "weekly_downloads": 0, "latest_published_at": None,
                "deprecated": False}
        base.update(fields)
        return base

    def test_published_to_registry_pass(self, make_repo):
        d = make_repo()
        d["registry"] = self._registry(exists=True)
        ok, _ = lint.s_published_to_registry(d)
        assert ok

    def test_published_to_registry_fail_when_missing(self, make_repo):
        d = make_repo()  # no registry data
        ok, _ = lint.s_published_to_registry(d)
        assert not ok

    def test_published_to_registry_fail_when_404(self, make_repo):
        d = make_repo()
        d["registry"] = self._registry(exists=False)
        ok, _ = lint.s_published_to_registry(d)
        assert not ok

    def test_recent_publish_pass(self, make_repo):
        from datetime import datetime, timedelta, timezone
        recent = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        d = make_repo()
        d["registry"] = self._registry(latest_published_at=recent)
        ok, _ = lint.s_recent_publish(d)
        assert ok

    def test_recent_publish_fail_old(self, make_repo):
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        d = make_repo()
        d["registry"] = self._registry(latest_published_at=old)
        ok, _ = lint.s_recent_publish(d)
        assert not ok

    def test_recent_publish_fail_no_data(self, make_repo):
        d = make_repo()
        ok, _ = lint.s_recent_publish(d)
        assert not ok

    def test_not_deprecated_pass(self, make_repo):
        d = make_repo()
        d["registry"] = self._registry(deprecated=False)
        ok, _ = lint.s_not_deprecated(d)
        assert ok

    def test_not_deprecated_fail_when_flagged(self, make_repo):
        d = make_repo()
        d["registry"] = self._registry(deprecated=True)
        ok, _ = lint.s_not_deprecated(d)
        assert not ok

    def test_weekly_downloads_meaningful_pass(self, make_repo):
        d = make_repo()
        d["registry"] = self._registry(weekly_downloads=50)
        ok, _ = lint.s_weekly_downloads_meaningful(d)
        assert ok

    def test_weekly_downloads_meaningful_fail_low(self, make_repo):
        d = make_repo()
        d["registry"] = self._registry(weekly_downloads=3)
        ok, _ = lint.s_weekly_downloads_meaningful(d)
        assert not ok

    def test_weekly_downloads_fail_no_data(self, make_repo):
        d = make_repo()
        ok, _ = lint.s_weekly_downloads_meaningful(d)
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
