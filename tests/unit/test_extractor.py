"""Tests for linter/extractor.py — static AST / regex tool extraction.

Each test feeds a synthetic source snippet and asserts that the extractor
finds the expected tool name + description. Realistic fixtures cover the
common SDK shapes (TypeScript MCP SDK, Python @mcp.tool, FastMCP, Go SDK).
"""
from __future__ import annotations
import pytest

import extractor


# ---------------------------------------------------------------------------
# Python AST extractor
# ---------------------------------------------------------------------------

class TestPythonExtractor:
    def test_basic_decorator_no_parens(self):
        src = '''
@mcp.tool
def list_rows(table: str) -> list:
    """List all rows in a table."""
    return []
'''
        tools = extractor.extract_python(src)
        assert len(tools) == 1
        assert tools[0]["name"] == "list_rows"
        assert tools[0]["description"] == "List all rows in a table."
        assert tools[0]["input_keys"] == ["table"]

    def test_decorator_with_parens(self):
        src = '''
@mcp.tool()
def query(sql: str, limit: int = 100) -> list:
    """Execute a SQL query."""
    pass
'''
        tools = extractor.extract_python(src)
        assert tools[0]["name"] == "query"
        assert tools[0]["input_keys"] == ["sql", "limit"]

    def test_explicit_name_kwarg(self):
        src = '''
@mcp.tool(name="custom_name")
def actual_function():
    """Doc."""
    pass
'''
        tools = extractor.extract_python(src)
        assert tools[0]["name"] == "custom_name"

    def test_explicit_name_positional(self):
        src = '''
@mcp.tool("position-name")
def fn():
    """."""
    pass
'''
        tools = extractor.extract_python(src)
        assert tools[0]["name"] == "position-name"

    def test_multiple_decorator_handles(self):
        # FastMCP uses 'app', some examples use 'server' or 'mcp'
        src = '''
@server.tool()
def tool_a():
    """A."""
    pass

@app.tool()
def tool_b():
    """B."""
    pass

@mcp.tool()
def tool_c():
    """C."""
    pass
'''
        names = sorted(t["name"] for t in extractor.extract_python(src))
        assert names == ["tool_a", "tool_b", "tool_c"]

    def test_async_function_supported(self):
        src = '''
@mcp.tool()
async def fetch_url(url: str):
    """Fetch a URL."""
    return await ...
'''
        tools = extractor.extract_python(src)
        assert tools[0]["name"] == "fetch_url"

    def test_non_tool_decorators_ignored(self):
        src = '''
@cache
def normal_function():
    """Not a tool."""
    pass

@mcp.tool()
def real_tool():
    """Yes."""
    pass
'''
        tools = extractor.extract_python(src)
        assert len(tools) == 1
        assert tools[0]["name"] == "real_tool"

    def test_self_cls_not_in_input_keys(self):
        src = '''
class Server:
    @mcp.tool()
    def method(self, x: int):
        """Method tool."""
        pass
'''
        tools = extractor.extract_python(src)
        assert "self" not in tools[0]["input_keys"]
        assert tools[0]["input_keys"] == ["x"]

    def test_syntax_error_returns_empty(self):
        # Extractor must be robust — never crash a pipeline run.
        tools = extractor.extract_python("def broken(:")
        assert tools == []


# ---------------------------------------------------------------------------
# TypeScript regex extractor
# ---------------------------------------------------------------------------

class TestTypeScriptExtractor:
    def test_server_tool_call(self):
        src = '''
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
const server = new Server({});
server.tool('browser_navigate', schema, async (args) => { ... });
server.tool("browser_click", { description: "Click an element" }, handler);
'''
        tools = extractor.extract_typescript(src)
        names = sorted(t["name"] for t in tools)
        assert names == ["browser_click", "browser_navigate"]

    def test_addtool_form(self):
        src = '''
addTool('my_tool', { description: 'Does the thing' }, async () => {});
'''
        tools = extractor.extract_typescript(src)
        assert tools[0]["name"] == "my_tool"

    def test_inline_tool_object_in_array(self):
        src = '''
const tools = [
  { name: "tool_one", description: "First tool" },
  { name: "tool_two", description: "Second" },
];
'''
        tools = extractor.extract_typescript(src)
        names = sorted(t["name"] for t in tools)
        assert names == ["tool_one", "tool_two"]
        for t in tools:
            assert t["description"] is not None

    def test_dynamic_call_skipped(self):
        # server.tool(myVariable, ...) — no string literal, can't extract.
        src = '''
const name = "dyn";
server.tool(name, schema, handler);
'''
        tools = extractor.extract_typescript(src)
        assert tools == []

    def test_dedupes_across_register_and_object_form(self):
        src = '''
server.tool('foo', schema, h);
const meta = [{ name: "foo", description: "Foo tool" }];
'''
        tools = extractor.extract_typescript(src)
        assert len(tools) == 1
        assert tools[0]["description"] == "Foo tool"


# ---------------------------------------------------------------------------
# Go regex extractor
# ---------------------------------------------------------------------------

class TestGoExtractor:
    def test_mcp_newtool(self):
        src = '''
package main
import "github.com/mark3labs/mcp-go/server"
func main() {
    s := server.NewMCPServer()
    s.AddTool(mcp.NewTool("query", schema), handler)
    s.AddTool(mcp.NewTool("execute", schema), handler)
}
'''
        tools = extractor.extract_go(src)
        names = sorted(t["name"] for t in tools)
        assert names == ["execute", "query"]


# ---------------------------------------------------------------------------
# extract_from_repo — full pipeline driver
# ---------------------------------------------------------------------------

class TestExtractFromRepo:
    def test_python_repo(self, make_repo):
        repo = make_repo(
            owner="example", name="py-mcp",
            source_files={"server.py": (
                '@mcp.tool()\n'
                'def add(x: int, y: int):\n'
                '    """Add two numbers."""\n'
                '    return x + y\n'
            )},
        )
        result = extractor.extract_from_repo(repo)
        assert result["extraction_method"] == "ast_python"
        assert result["tools_count"] == 1
        assert result["tools"][0]["name"] == "add"
        assert result["extraction_confidence"] >= 0.7

    def test_typescript_repo(self, make_repo):
        repo = make_repo(
            owner="example", name="ts-mcp",
            source_files={"src/index.ts": (
                "server.tool('hello', { description: 'Say hi' }, async () => 'hi');\n"
            )},
        )
        result = extractor.extract_from_repo(repo)
        assert result["extraction_method"] == "regex_typescript"
        assert result["tools_count"] == 1
        assert result["tools"][0]["name"] == "hello"

    def test_no_source_files_returns_empty(self, make_repo):
        repo = make_repo(owner="example", name="empty", source_files={})
        result = extractor.extract_from_repo(repo)
        assert result["extraction_method"] == "none"
        assert result["tools_count"] == 0
        assert result["extraction_confidence"] == 0.0

    def test_returned_shape_is_complete(self, make_repo):
        repo = make_repo(
            owner="x", name="y",
            source_files={"main.py": "@mcp.tool()\ndef t():\n    '''d'''\n    pass\n"},
        )
        result = extractor.extract_from_repo(repo)
        for key in ("repo", "slug", "extraction_method", "extraction_confidence",
                    "tools_count", "tools", "source_files_scanned"):
            assert key in result

    def test_summarize_for_index(self, make_repo):
        repo = make_repo(
            owner="x", name="y",
            source_files={"main.py": (
                "\n".join(f"@mcp.tool()\ndef t{i}():\n    '''d'''\n    pass" for i in range(15))
            )},
        )
        result = extractor.extract_from_repo(repo)
        summary = extractor.summarize_for_index(result)
        assert summary["tool_count"] == 15
        assert len(summary["tool_names_preview"]) == 10  # capped
        assert summary["extraction_method"] == "ast_python"
