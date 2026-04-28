"""Tests for classify.classify_kind — the function that decides whether a
repo is a server, client, framework, tool, or ambiguous, plus the subkind
for servers.

Each test corresponds to a real-world signal pattern we want to classify
correctly. When this file goes red, we have a regression in classification.
"""
from __future__ import annotations
import json
import pytest

import classify


def kind_of(d):
    return classify.classify_kind(d)[0]


def subkind_of(d):
    return classify.classify_kind(d)[1]


def confidence_of(d):
    return classify.classify_kind(d)[2]


# ---------------------------------------------------------------------------
# Server detection
# ---------------------------------------------------------------------------

class TestServerDetection:
    def test_typescript_sdk_dep_in_package_json(self, repo_server_typescript_sdk):
        kind, sub, conf, _ = classify.classify_kind(repo_server_typescript_sdk)
        assert kind == "server"
        assert sub == "integration"
        assert conf >= 0.9  # Run-pattern in source = high confidence

    def test_python_pep621_list_style_dep(self, repo_server_python_pep621):
        # Regression: serena's "mcp==1.27.0" in [project.dependencies] list
        # was excluded by stricter prefilter regex before fix.
        kind, _, _, _ = classify.classify_kind(repo_server_python_pep621)
        assert kind == "server"

    def test_python_poetry_table_style_dep(self, make_repo):
        d = make_repo(
            owner="x", name="thing-mcp",
            description="An MCP server",
            pkg={"pyproject.toml": '[tool.poetry.dependencies]\nmcp = "^1.0"\n'},
        )
        assert kind_of(d) == "server"

    def test_python_requirements_txt_style(self, make_repo):
        d = make_repo(
            owner="x", name="thing-mcp",
            description="An MCP server",
            pkg={"setup.cfg": "[options]\ninstall_requires =\n    mcp>=1.0\n"},
        )
        assert kind_of(d) == "server"

    def test_go_mark3labs_import(self, repo_server_go_imports):
        # Detected via source_files even when go.mod doesn't list it.
        kind, _, _, _ = classify.classify_kind(repo_server_go_imports)
        assert kind == "server"

    def test_go_official_sdk_import(self, make_repo):
        d = make_repo(
            owner="example", name="mcp-go-thing",
            description="An MCP server",
            pkg={"go.mod": "module x\ngo 1.22\n"},
            source_files={
                "main.go": 'import "github.com/modelcontextprotocol/go-sdk/server"\n',
            },
        )
        assert kind_of(d) == "server"

    def test_npm_modelcontextprotocol_scope(self, make_repo):
        d = make_repo(
            pkg={"package.json": '{"dependencies": {"@modelcontextprotocol/sdk": "1.0"}}'},
        )
        assert kind_of(d) == "server"

    def test_run_pattern_beats_phrase(self, make_repo):
        # If a repo has both server-run pattern AND framework phrases
        # (which can happen — server README mentioning "build with FastMCP"),
        # run pattern wins.
        d = make_repo(
            description="A framework for building MCP servers",  # framework phrase
            source_files={
                "src/index.ts": "new Server({}).run();\nserver.tool('x',{},async()=>{});\n",
            },
        )
        assert kind_of(d) == "server"

    def test_mcpservers_config_in_readme(self, make_repo):
        d = make_repo(
            description="Some description",
            readme='Add to your config:\n```json\n{"mcpServers": {"x": {}}}\n```',
            pkg={},  # no SDK dep
        )
        assert kind_of(d) == "server"

    def test_name_pattern_fallback_mcp_prefix(self, make_repo):
        d = make_repo(name="mcp-cool-thing", description="cool thing", pkg={})
        assert kind_of(d) == "server"

    def test_name_pattern_fallback_mcp_suffix(self, make_repo):
        d = make_repo(name="cool-thing-mcp", description="cool thing", pkg={})
        assert kind_of(d) == "server"

    def test_name_pattern_fallback_mcp_in_middle(self, make_repo):
        # Regression: github-mcp-server didn't match before name pattern widening.
        d = make_repo(name="github-mcp-server", description="GitHub server")
        assert kind_of(d) == "server"


# ---------------------------------------------------------------------------
# Server subkinds
# ---------------------------------------------------------------------------

class TestSubkinds:
    def test_default_subkind_is_integration(self, repo_server_typescript_sdk):
        _, sub, _, _ = classify.classify_kind(repo_server_typescript_sdk)
        assert sub == "integration"

    def test_aggregator_phrase(self, make_repo):
        d = make_repo(
            owner="zapier", name="mcp",
            description="One MCP for every app — gateway to thousands of integrations",
            pkg={"package.json": '{"dependencies":{"@modelcontextprotocol/sdk":"1"}}'},
        )
        _, sub, _, _ = classify.classify_kind(d)
        assert sub == "aggregator"

    def test_prompt_tool_by_name(self, make_repo):
        d = make_repo(
            owner="modelcontextprotocol", name="sequential-thinking",
            description="Reasoning aid",
            pkg={"package.json": '{"dependencies":{"@modelcontextprotocol/sdk":"1"}}'},
        )
        _, sub, _, _ = classify.classify_kind(d)
        assert sub == "prompt-tool"

    def test_suite_allowlist_awslabs(self, repo_suite_awslabs):
        kind, sub, conf, _ = classify.classify_kind(repo_suite_awslabs)
        assert kind == "server"
        assert sub == "agent-product"
        assert conf == 1.0  # Allowlist = full confidence

    def test_suite_allowlist_modelcontextprotocol_servers(self, make_repo):
        d = make_repo(owner="modelcontextprotocol", name="servers")
        kind, sub, _, _ = classify.classify_kind(d)
        assert kind == "server"
        assert sub == "agent-product"


# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------

class TestFrameworkDetection:
    def test_fastmcp_framework_phrase(self, repo_framework_fastmcp):
        kind, _, _, _ = classify.classify_kind(repo_framework_fastmcp)
        assert kind == "framework"

    def test_official_sdk_repo_allowlist(self, make_repo):
        d = make_repo(owner="modelcontextprotocol", name="python-sdk")
        kind, _, conf, _ = classify.classify_kind(d)
        assert kind == "framework"
        assert conf == 1.0

    def test_framework_phrase_blocked_when_sdk_dep_present(self, make_repo):
        # A server README can quote "framework for building MCP" while itself
        # consuming the SDK. SDK dep dominates → server.
        d = make_repo(
            description="Built on the framework for building MCP. This is a server.",
            pkg={"package.json": '{"dependencies":{"@modelcontextprotocol/sdk":"1"}}'},
        )
        assert kind_of(d) == "server"


# ---------------------------------------------------------------------------
# Client / tool / ambiguous
# ---------------------------------------------------------------------------

class TestClientDetection:
    def test_explicit_client_phrase(self, repo_client):
        kind, _, _, _ = classify.classify_kind(repo_client)
        assert kind == "client"

    def test_client_phrase_blocked_when_sdk_dep_present(self, make_repo):
        # Server READMEs often say "use with any MCP client" — that incidental
        # phrase should NOT flip a SDK-using repo to client.
        d = make_repo(
            description="Server that works with any MCP client implementation",
            pkg={"package.json": '{"dependencies":{"@modelcontextprotocol/sdk":"1"}}'},
        )
        assert kind_of(d) == "server"


class TestToolDetection:
    def test_inspector_name_token(self, repo_inspector_tool):
        kind, _, _, _ = classify.classify_kind(repo_inspector_tool)
        assert kind == "tool"

    def test_devtools_name_token(self, make_repo):
        d = make_repo(name="mcp-devtools", description="dev utilities for MCP")
        assert kind_of(d) == "tool"


class TestAmbiguous:
    def test_no_signals_yields_ambiguous(self, repo_ambiguous):
        kind, sub, conf, reason = classify.classify_kind(repo_ambiguous)
        assert kind == "ambiguous"
        assert sub == ""
        assert conf < 0.5
        assert reason  # Always include a reason for traceability


# ---------------------------------------------------------------------------
# Returned tuple shape contract
# ---------------------------------------------------------------------------

class TestReturnShape:
    def test_returns_4_tuple(self, repo_server_typescript_sdk):
        result = classify.classify_kind(repo_server_typescript_sdk)
        assert isinstance(result, tuple)
        assert len(result) == 4
        kind, subkind, confidence, reason = result
        assert isinstance(kind, str)
        assert isinstance(subkind, str)
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0
        assert isinstance(reason, str)

    @pytest.mark.parametrize("fixture", [
        "repo_server_typescript_sdk",
        "repo_server_python_pep621",
        "repo_framework_fastmcp",
        "repo_inspector_tool",
        "repo_client",
        "repo_ambiguous",
        "repo_suite_awslabs",
    ])
    def test_kind_in_valid_set(self, fixture, request):
        d = request.getfixturevalue(fixture)
        kind, _, _, _ = classify.classify_kind(d)
        assert kind in {"server", "client", "framework", "tool", "ambiguous"}

    @pytest.mark.parametrize("fixture", [
        "repo_server_typescript_sdk",
        "repo_server_python_pep621",
        "repo_suite_awslabs",
    ])
    def test_server_subkind_is_valid(self, fixture, request):
        d = request.getfixturevalue(fixture)
        kind, sub, _, _ = classify.classify_kind(d)
        assert kind == "server"
        assert sub in {"integration", "aggregator", "prompt-tool", "agent-product"}
