"""Shared pytest fixtures.

Tests are stdlib-friendly: only pytest itself is added as devDep. We don't
import the linter as a package because the linter is run as a script
(`python linter/lint.py`); instead we add `linter/` to sys.path here and
import the modules directly. Keeps test wiring out of production code.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
LINTER = ROOT / "linter"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Make linter modules importable as `import classify`, `import lint` etc.
if str(LINTER) not in sys.path:
    sys.path.insert(0, str(LINTER))


# ---------------------------------------------------------------------------
# Repo-shape factory: build the dict that lint/classify expect
# ---------------------------------------------------------------------------

def _make_repo(
    *,
    owner: str = "acme",
    name: str = "mcp-thing",
    description: str = "An MCP server for X",
    topics: list[str] | None = None,
    stars: int = 100,
    language: str | None = "TypeScript",
    license_spdx: str | None = "MIT",
    pushed_at: str = "2026-04-01T12:00:00Z",
    archived: bool = False,
    pkg: dict[str, str] | None = None,
    readme: str = "",
    source_files: dict[str, str] | None = None,
    has_ci: bool = False,
    top_paths: list[str] | None = None,
    releases_count: int = 0,
    tags_count: int = 0,
    latest_release_date: str | None = None,
    commits_90d: list[dict] | None = None,
    closed_pulls_recent: list[dict] | None = None,
    releases_full: list[dict] | None = None,
) -> dict[str, Any]:
    """Construct a crawler-shaped cache entry for one repo. Defaults are sane.
    Pass kwargs to override. Used by every test that wants a repo dict."""
    return {
        "repo": {
            "owner": {"login": owner},
            "name": name,
            "full_name": f"{owner}/{name}",
            "description": description,
            "topics": topics or [],
            "stargazers_count": stars,
            "language": language,
            "license": {"spdx_id": license_spdx} if license_spdx else None,
            "pushed_at": pushed_at,
            "archived": archived,
        },
        "readme": readme,
        "pkg": pkg or {},
        "source_files": source_files or {},
        "has_ci": has_ci,
        "top_paths": top_paths or [],
        "releases_count": releases_count,
        "tags_count": tags_count,
        "latest_release_date": latest_release_date,
        "commits_90d": commits_90d or [],
        "total_commits_sample": [{"sha": "a"}, {"sha": "b"}],
        "closed_pulls_recent": closed_pulls_recent or [],
        "releases_full": releases_full or [],
    }


@pytest.fixture
def make_repo():
    """Factory fixture — call inside tests as `make_repo(name='foo', ...)`."""
    return _make_repo


@pytest.fixture
def fixtures_dir():
    """Path to tests/fixtures/. Tests can load JSON fixtures from here."""
    return FIXTURES


@pytest.fixture
def load_fixture(fixtures_dir):
    """Load a named JSON fixture into a dict."""
    def _load(name: str) -> dict:
        path = fixtures_dir / name
        if not path.exists():
            pytest.fail(f"fixture not found: {path}")
        return json.loads(path.read_text())
    return _load


# ---------------------------------------------------------------------------
# Pre-built canonical repo fixtures — the kinds we care about classifying
# ---------------------------------------------------------------------------

@pytest.fixture
def repo_server_typescript_sdk(make_repo):
    """A typical TS-based MCP server: SDK dep in package.json + server-run pattern."""
    return make_repo(
        owner="example",
        name="example-mcp",
        description="MCP server for example.com integration",
        topics=["mcp", "mcp-server"],
        pkg={
            "package.json": json.dumps({
                "name": "@example/mcp",
                "dependencies": {"@modelcontextprotocol/sdk": "^1.0.0"},
            }),
        },
        source_files={
            "src/index.ts": (
                "import { Server } from '@modelcontextprotocol/sdk/server/index.js';\n"
                "const server = new Server(...);\n"
                "server.tool('do_thing', schema, async () => {});\n"
            ),
        },
    )


@pytest.fixture
def repo_server_python_pep621(make_repo):
    """Python server with mcp dep listed in PEP 621 dependencies array."""
    return make_repo(
        owner="example",
        name="serena-like",
        description="MCP toolkit for coding",
        topics=["mcp"],
        pkg={
            "pyproject.toml": (
                '[project]\n'
                'name = "thing"\n'
                'dependencies = [\n'
                '  "requests==2.33.0",\n'
                '  "mcp==1.27.0",\n'
                ']\n'
            ),
        },
    )


@pytest.fixture
def repo_server_go_imports(make_repo):
    """Go server: mcp-go imported in source, no go.mod entry detected."""
    return make_repo(
        owner="example",
        name="github-like-mcp-server",
        description="Go server for github operations via MCP",
        topics=["mcp"],
        pkg={"go.mod": "module example.com/foo\ngo 1.22\n"},
        source_files={
            "main.go": (
                'package main\n'
                'import "github.com/mark3labs/mcp-go/server"\n'
                'func main() { server.NewMCPServer(...) }\n'
            ),
        },
    )


@pytest.fixture
def repo_framework_fastmcp(make_repo):
    """A framework FOR BUILDING servers, not a server."""
    return make_repo(
        owner="jlowin",
        name="fastmcp",
        description="A framework for building MCP servers in Python",
        topics=["mcp", "framework"],
        pkg={"pyproject.toml": '[project]\nname = "fastmcp"\n'},
    )


@pytest.fixture
def repo_inspector_tool(make_repo):
    """An MCP inspector / devtool, NOT a server."""
    return make_repo(
        owner="modelcontextprotocol",
        name="inspector",
        description="Visual inspector for MCP servers",
        topics=["mcp", "devtools"],
    )


@pytest.fixture
def repo_client(make_repo):
    """An MCP client implementation."""
    return make_repo(
        owner="someone",
        name="my-mcp-client",
        description="This is an MCP client for use in IDEs",
    )


@pytest.fixture
def repo_ambiguous(make_repo):
    """No decisive signal — should classify as ambiguous."""
    return make_repo(
        owner="someone",
        name="random-thing",
        description="A thing that does random stuff",
        topics=["ai"],
    )


@pytest.fixture
def repo_suite_awslabs(make_repo):
    """Multi-server suite — handled by allowlist."""
    return make_repo(
        owner="awslabs",
        name="mcp",
        description="AWS MCP servers",
        topics=["mcp", "aws"],
    )
