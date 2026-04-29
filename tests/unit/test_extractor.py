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

    def test_variable_receiver_fastmcp_pattern(self):
        # G3 (Opus finding): real FastMCP code does
        #   my_mcp = FastMCP("Foo")
        #   @my_mcp.tool()
        #   def thing(): ...
        # Our hardcoded receiver list (mcp/server/app/fastmcp) misses 'my_mcp'.
        # Detect by tracing assignments to FastMCP() / Server() / etc.
        src = '''
from mcp.server.fastmcp import FastMCP

my_mcp = FastMCP("MyServer")

@my_mcp.tool()
def custom_tool(query: str):
    """Run a custom query."""
    return query
'''
        tools = extractor.extract_python(src)
        assert len(tools) == 1
        assert tools[0]["name"] == "custom_tool"
        assert tools[0]["description"] == "Run a custom query."

    def test_variable_receiver_with_aliased_import(self):
        src = '''
from mcp.server.fastmcp import FastMCP as _MCP
srv = _MCP("X")

@srv.tool()
def aliased():
    """Aliased server tool."""
    pass
'''
        tools = extractor.extract_python(src)
        assert len(tools) == 1
        assert tools[0]["name"] == "aliased"

    def test_variable_receiver_via_server_constructor(self):
        # Same pattern using `Server` from sdk
        src = '''
from mcp.server import Server
the_server = Server("foo")

@the_server.tool()
def foo_tool():
    """Foo."""
    pass
'''
        tools = extractor.extract_python(src)
        assert len(tools) == 1
        assert tools[0]["name"] == "foo_tool"

    def test_unrelated_variable_decorator_still_ignored(self):
        # Regression: don't flip and start matching every @x.tool decorator.
        # If the variable wasn't assigned to a known MCP class, no match.
        src = '''
class Cache:
    def tool(self): pass
random = Cache()

@random.tool()
def not_a_tool():
    """Not an MCP tool."""
    pass
'''
        tools = extractor.extract_python(src)
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

    def test_real_world_inputSchema_with_nested_braces(self):
        # G2 (Opus finding): EVERY real MCP TS server uses nested {} in
        # inputSchema. Form 2 regex disallowed nested braces, silently
        # missing all of them. This is the catch.
        src = '''
const TOOLS = [
  {
    name: "browser_navigate",
    description: "Navigate to a URL",
    inputSchema: {
      type: "object",
      properties: { url: { type: "string" } },
      required: ["url"]
    }
  },
  {
    name: "browser_click",
    description: "Click an element",
    inputSchema: { type: "object", properties: { selector: { type: "string" } } }
  }
];
'''
        tools = extractor.extract_typescript(src)
        names = sorted(t["name"] for t in tools)
        assert names == ["browser_click", "browser_navigate"]
        descs = {t["name"]: t["description"] for t in tools}
        assert descs["browser_navigate"] == "Navigate to a URL"
        assert descs["browser_click"] == "Click an element"

    def test_object_form_with_setRequestHandler_array(self):
        # The other common pattern — tools/list returns an array of
        # tool descriptors, each with nested inputSchema.
        src = '''
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "read_file",
      description: "Read file contents",
      inputSchema: {
        type: "object",
        properties: { path: { type: "string", description: "absolute path" } },
        required: ["path"]
      }
    }
  ]
}));
'''
        tools = extractor.extract_typescript(src)
        assert len(tools) == 1
        assert tools[0]["name"] == "read_file"
        assert tools[0]["description"] == "Read file contents"


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


class TestDetectSubServers:
    """Phase K: suite repos (awslabs/mcp, modelcontextprotocol/servers,
    googleapis/mcp-toolbox) bundle multiple MCP servers in subdirectories
    like packages/<svc>/ or src/<svc>/. Parent gets a sub_servers[] field
    so an agent calling vet on the parent learns about each sub-server."""

    def test_no_subdirs_returns_empty(self, make_repo):
        d = make_repo(top_paths=["README.md", "LICENSE", "package.json"])
        subs = extractor.detect_sub_servers(d)
        assert subs == []

    def test_packages_dir_with_subpackages(self, make_repo):
        d = make_repo(
            top_paths=["packages", "README.md"],
            source_files={
                "packages/aws-cdk-mcp-server/server.py": (
                    "@mcp.tool()\ndef cdk_synth():\n    '''Synth CDK.'''\n    pass\n"
                ),
                "packages/dynamodb-mcp-server/server.py": (
                    "@mcp.tool()\ndef get_item():\n    '''Get DynamoDB item.'''\n    pass\n"
                    "@mcp.tool()\ndef put_item():\n    '''Put DynamoDB item.'''\n    pass\n"
                ),
            },
        )
        subs = extractor.detect_sub_servers(d)
        assert len(subs) == 2
        names = sorted(s["name"] for s in subs)
        assert names == ["aws-cdk-mcp-server", "dynamodb-mcp-server"]

    def test_sub_servers_have_tools_extracted(self, make_repo):
        d = make_repo(
            top_paths=["packages"],
            source_files={
                "packages/foo-server/server.py": (
                    "@mcp.tool()\ndef alpha():\n    '''A.'''\n    pass\n"
                    "@mcp.tool()\ndef beta():\n    '''B.'''\n    pass\n"
                ),
            },
        )
        subs = extractor.detect_sub_servers(d)
        assert len(subs) == 1
        sub = subs[0]
        assert sub["name"] == "foo-server"
        assert sub["subpath"] == "packages/foo-server"
        assert sub["tools_count"] == 2
        # Should include the actual tool names
        tool_names = sorted(t["name"] for t in sub["tools"])
        assert tool_names == ["alpha", "beta"]

    def test_src_dir_pattern(self, make_repo):
        # modelcontextprotocol/servers uses src/<server>/ layout
        d = make_repo(
            top_paths=["src"],
            source_files={
                "src/filesystem/index.ts": (
                    "server.tool('read_file', schema, h);\n"
                    "server.tool('write_file', schema, h);\n"
                ),
                "src/git/index.ts": "server.tool('clone', schema, h);\n",
            },
        )
        subs = extractor.detect_sub_servers(d)
        names = sorted(s["name"] for s in subs)
        assert names == ["filesystem", "git"]

    def test_sub_with_zero_tools_skipped(self, make_repo):
        # A subdir without any tool registration shouldn't be treated as a
        # sub-server — just a utility/lib directory.
        d = make_repo(
            top_paths=["packages"],
            source_files={
                "packages/utils/helper.py": "def some_helper(): pass\n",
            },
        )
        subs = extractor.detect_sub_servers(d)
        assert subs == []
