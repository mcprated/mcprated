#!/usr/bin/env python3
"""MCPRated AST extractor — pull each MCP server's exposed tools from source.

Why this exists:
  Catalog metadata answers "is this a server" but not "what does it do at
  the tool level". Without this, agents asking find_tool(intent="read postgres")
  can only land at the server level (e.g., supabase-mcp) and have to install
  + call tools/list to learn the actual surface. With extracted tools we can
  answer the agent's question with a specific tool name on a specific server,
  before any install.

Approach:
  Static analysis. Read the source files the crawler already cached
  (source_files dict) and look for the SDK-specific tool registration
  patterns. No code execution, no sandbox, deterministic.

Coverage:
  - Python: ast module, detects @mcp.tool / @mcp.tool() / @server.tool()
            decorators and FastMCP-style registrations.
  - TypeScript: regex on `server.tool('name', schema, handler)` and the
                lower-level `setRequestHandler('tools/list', () => [...])`.
                Not a real TS parser; ~75% pokrycie of real-world servers.
  - Go: regex on `mcp.NewTool(...)` and `server.AddTool(...)` constructions.

  Misses dynamic generation (`for x in things: server.tool(x, ...)`),
  factory functions, and anything where the tool name isn't a string literal.
  The 30% miss is the V6 sandbox-runtime territory.

Output:
  data/tools/<slug>.json per server with a stable shape:
    {
      "repo": "owner/name",
      "slug": "owner__name",
      "extraction_method": "ast_python|regex_typescript|regex_go|none",
      "extraction_confidence": float in [0, 1],
      "tools_count": int,
      "tools": [{"name": str, "description": str|None, "input_keys": list[str]}],
      "source_files_scanned": [list of paths]
    }

Stdlib only. Importable from lint.py to enrich per-server JSON with
tool_count + tools_summary.
"""
from __future__ import annotations
import ast as pyast
import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Python AST extractor — uses stdlib `ast` for full structural fidelity
# ---------------------------------------------------------------------------

# Class names whose constructed instances expose `.tool()` as MCP registration.
# Imported (potentially aliased) at module level — see _PyToolVisitor.visit_ImportFrom
# for how aliases are tracked.
_MCP_CLASS_NAMES = {"FastMCP", "Server", "MCPServer", "McpServer"}


class _PyToolVisitor(pyast.NodeVisitor):
    """Walk a Python AST collecting MCP tool registrations.

    Recognized patterns:
      @mcp.tool(...)            classic — fixed receiver name
      @server.tool(...)         alternate handle name
      @app.tool(...)            FastMCP convention
      @<var>.tool(...)          where <var> = FastMCP(...) | Server(...) | ...

    G3 (Opus finding): real FastMCP code does
        my_mcp = FastMCP("Foo")
        @my_mcp.tool()
        def thing(): ...
    The hardcoded receiver list missed 'my_mcp'. Now we trace assignments
    to MCP-class constructors AND import aliases (`from x import FastMCP as _MCP`)
    so any variable bound to such an instance is treated as a tool receiver.

    For each match we record the function name, its docstring (description),
    and the parameter names (input_keys) inferred from the signature.
    """

    def __init__(self):
        self.tools: list[dict[str, Any]] = []
        # Receiver names that act as MCP servers. Seeded with the legacy
        # hardcoded list for backward compatibility; extended dynamically
        # via assignments to MCP-class constructors.
        self.mcp_vars: set[str] = {"mcp", "server", "app", "fastmcp"}
        # Local names that resolve to MCP classes — e.g. with `from x import FastMCP`
        # the local name is "FastMCP"; with `import ... as _MCP` it's "_MCP".
        self.mcp_class_locals: set[str] = set(_MCP_CLASS_NAMES)

    def visit_ImportFrom(self, node):  # noqa: N802
        if node.module and node.module.startswith("mcp"):
            for alias in node.names or []:
                if alias.name in _MCP_CLASS_NAMES:
                    self.mcp_class_locals.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Assign(self, node):  # noqa: N802
        # Track `var = FastMCP(...)` etc. — the `var` then acts like `mcp` does.
        if isinstance(node.value, pyast.Call):
            func = node.value.func
            ctor_name: str | None = None
            if isinstance(func, pyast.Name):
                ctor_name = func.id
            elif isinstance(func, pyast.Attribute):
                ctor_name = func.attr
            if ctor_name and ctor_name in self.mcp_class_locals:
                for target in node.targets:
                    if isinstance(target, pyast.Name):
                        self.mcp_vars.add(target.id)
        self.generic_visit(node)

    def _is_tool_decorator(self, dec: pyast.expr) -> bool:
        # @<receiver>.tool  or  @<receiver>.tool(...)
        node = dec.func if isinstance(dec, pyast.Call) else dec
        return (
            isinstance(node, pyast.Attribute)
            and node.attr == "tool"
            and isinstance(node.value, pyast.Name)
            and node.value.id in self.mcp_vars
        )

    def _extract_decorator_name(self, dec: pyast.expr, fallback: str) -> str:
        """If @mcp.tool(name="x") was used, return "x"; else fallback."""
        if not isinstance(dec, pyast.Call):
            return fallback
        for kw in dec.keywords or []:
            if kw.arg == "name" and isinstance(kw.value, pyast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
        # Sometimes positional: @mcp.tool("name")
        if dec.args and isinstance(dec.args[0], pyast.Constant) and isinstance(dec.args[0].value, str):
            return dec.args[0].value
        return fallback

    def _visit_func(self, node: pyast.FunctionDef | pyast.AsyncFunctionDef):
        for dec in node.decorator_list:
            if self._is_tool_decorator(dec):
                name = self._extract_decorator_name(dec, node.name)
                doc = pyast.get_docstring(node)
                args = [
                    a.arg for a in node.args.args
                    if a.arg not in ("self", "cls")
                ]
                self.tools.append({
                    "name": name,
                    "description": (doc or "").strip().split("\n")[0][:200] or None,
                    "input_keys": args,
                })
                break
        self.generic_visit(node)

    def visit_FunctionDef(self, node):  # noqa: N802 (ast convention)
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        self._visit_func(node)


def extract_python(source: str) -> list[dict[str, Any]]:
    """Parse Python source, return list of tool dicts. Empty list on syntax
    error — extractor must never crash on a single bad file."""
    try:
        tree = pyast.parse(source)
    except SyntaxError:
        return []
    v = _PyToolVisitor()
    v.visit(tree)
    return v.tools


# ---------------------------------------------------------------------------
# TypeScript / JavaScript regex extractor — best-effort, no real TS parser.
#
# Patterns we catch:
#   server.tool('name', schema, async (...) => {})
#   server.tool("name", { description: '...' }, ...)
#   server.tool('name', { description, inputSchema }, ...)
#   addTool('name', ...)
#   { name: 'foo', ... } inside an array passed to setRequestHandler('tools/list')
# ---------------------------------------------------------------------------

# Matches `server.tool('name'` or `addTool("name"` etc. — the call-site
# registration form. Trailing comma anchor avoids `server.tool(myVar` (no
# string literal = dynamic, can't extract).
_TS_TOOL_REGISTER_RX = re.compile(
    r"""
    \b(?:server|mcp|app)?\.?(?:tool|addTool|registerTool)\s*\(
    \s*['"]([\w\-.]+)['"]               # tool name (group 1)
    \s*,                                 # next arg
    """,
    re.VERBOSE,
)

_TS_NAME_RX = re.compile(r"""\bname\s*:\s*["']([\w\-.]+)["']""")
_TS_DESC_RX = re.compile(r"""\bdescription\s*:\s*["']([^"']{0,200})["']""")


def _balanced_brace_blocks(text: str, max_block_size: int = 8000):
    """Yield bodies of every balanced `{...}` block at every nesting level.

    G2 (Opus finding): real MCP TS code wraps tool descriptors in arbitrarily
    nested structures — `setRequestHandler(..., () => ({ tools: [{ name: ..., inputSchema: {...} }] }))`
    puts the descriptor at depth 2. Yielding only depth-0 blocks misses it.
    Yielding every level keeps the work proportional to brace count
    (cheap), and the per-block name/description regex naturally filters
    non-descriptor blocks.

    Stack-based walk so blocks come out as they close (innermost first).
    max_block_size guards against pathological inputs.
    """
    stack: list[int] = []
    for i, c in enumerate(text):
        if c == "{":
            stack.append(i)
        elif c == "}" and stack:
            start = stack.pop()
            body = text[start + 1 : i]
            if len(body) <= max_block_size:
                yield body


def _strip_nested_braces(body: str) -> str:
    """Drop everything inside `{...}` nested levels of `body`.

    Keeps only top-level content of an object literal — so we can apply
    `name:` / `description:` regex without accidentally matching inner
    schema fields like `properties.path.description`.
    """
    out = []
    depth = 0
    for c in body:
        if c == "{":
            depth += 1
            continue
        if c == "}":
            if depth > 0:
                depth -= 1
            continue
        if depth == 0:
            out.append(c)
    return "".join(out)


def extract_typescript(source: str) -> list[dict[str, Any]]:
    """Best-effort. Returns deduplicated tool list across two patterns:
    direct `server.tool('name', ...)` calls AND inline `{ name: 'x', description: 'y' }`
    objects in tools/list array returns.
    """
    seen: dict[str, dict[str, Any]] = {}

    # Form 1: registration call sites
    for m in _TS_TOOL_REGISTER_RX.finditer(source):
        name = m.group(1)
        seen.setdefault(name, {"name": name, "description": None, "input_keys": []})

    # Form 2: object literals with name + (optional) description.
    # Walk balanced braces so nested `inputSchema: {...}` doesn't break us.
    for body in _balanced_brace_blocks(source):
        top = _strip_nested_braces(body)
        name_m = _TS_NAME_RX.search(top)
        if not name_m:
            continue
        name = name_m.group(1)
        desc_m = _TS_DESC_RX.search(top)
        desc = desc_m.group(1).strip() if desc_m else None
        if name in seen:
            if desc and not seen[name]["description"]:
                seen[name]["description"] = desc[:200]
        else:
            seen[name] = {
                "name": name,
                "description": desc[:200] if desc else None,
                "input_keys": [],
            }

    return list(seen.values())


# ---------------------------------------------------------------------------
# Go regex extractor — mcp.NewTool("name", ...) and server.AddTool(...)
# ---------------------------------------------------------------------------

_GO_TOOL_RX = re.compile(
    r"""
    \b(?:mcp\.NewTool|server\.AddTool|s\.AddTool)\s*\(
    \s*"([\w\-.]+)"                      # name
    """,
    re.VERBOSE,
)


def extract_go(source: str) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for m in _GO_TOOL_RX.finditer(source):
        name = m.group(1)
        seen.setdefault(name, {"name": name, "description": None, "input_keys": []})
    return list(seen.values())


# ---------------------------------------------------------------------------
# Driver — picks extractor by file extension
# ---------------------------------------------------------------------------

EXTRACTORS = {
    ".py":  ("ast_python",       extract_python),
    ".ts":  ("regex_typescript", extract_typescript),
    ".tsx": ("regex_typescript", extract_typescript),
    ".js":  ("regex_typescript", extract_typescript),
    ".mjs": ("regex_typescript", extract_typescript),
    ".go":  ("regex_go",         extract_go),
    ".rs":  ("regex_typescript", extract_typescript),  # close-enough for `Tool::new("name")`
}


def extract_from_repo(cache_entry: dict) -> dict[str, Any]:
    """Run the extractor across a repo's cached source_files. Returns the
    full output shape (see module docstring)."""
    repo_meta = cache_entry.get("repo", {})
    owner = (repo_meta.get("owner") or {}).get("login") or "?"
    name = repo_meta.get("name") or "?"
    full_name = f"{owner}/{name}"
    slug = f"{owner}__{name}"
    sources = cache_entry.get("source_files") or {}

    method = "none"
    all_tools: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    files_scanned: list[str] = []

    for path, body in sources.items():
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        m = EXTRACTORS.get(ext)
        if not m or not isinstance(body, str):
            continue
        method_name, fn = m
        method = method_name  # last extractor wins; usually all sources are same lang
        files_scanned.append(path)
        for t in fn(body):
            if t["name"] not in seen_names:
                seen_names.add(t["name"])
                all_tools.append(t)

    # Confidence heuristic: AST > regex; more files scanned = higher confidence.
    if method == "ast_python":
        confidence = 0.9 if all_tools else 0.4
    elif method.startswith("regex_"):
        confidence = 0.7 if all_tools else 0.3
    else:
        confidence = 0.0

    return {
        "repo": full_name,
        "slug": slug,
        "extraction_method": method,
        "extraction_confidence": confidence,
        "tools_count": len(all_tools),
        "tools": all_tools,
        "source_files_scanned": files_scanned,
    }


# ---------------------------------------------------------------------------
# Public helper used by lint.py to enrich per-server JSON output
# ---------------------------------------------------------------------------

def detect_sub_servers(cache_entry: dict) -> list[dict[str, Any]]:
    """Phase K: enumerate sub-servers inside a suite repo.

    Suite repos (awslabs/mcp, modelcontextprotocol/servers, googleapis/mcp-toolbox)
    bundle multiple independent MCP servers in `packages/<x>/` or `src/<x>/`.
    For each subdir that contains tool registrations, return:
        {name, subpath, tools_count, tools[], extraction_method}

    Detection: group cached source_files by their first-two-path-segments
    when those start with `packages/` or `src/`; run extractor over each
    group's source files; emit only groups with tools_count > 0 (utility
    subdirs without tool registrations aren't sub-servers).
    """
    sources = cache_entry.get("source_files") or {}
    if not sources:
        return []

    # Group source files by sub-server root (first two path segments
    # when prefix is packages/ or src/)
    groups: dict[str, dict[str, str]] = {}
    for path, body in sources.items():
        if not isinstance(path, str) or not isinstance(body, str):
            continue
        parts = path.split("/", 2)
        if len(parts) < 3:
            continue
        if parts[0] not in ("packages", "src"):
            continue
        sub_root = f"{parts[0]}/{parts[1]}"
        groups.setdefault(sub_root, {})[path] = body

    out: list[dict[str, Any]] = []
    for sub_root, sub_sources in sorted(groups.items()):
        # Run the same extractor logic on this sub-group
        fake_entry = {"repo": cache_entry.get("repo", {}), "source_files": sub_sources}
        extraction = extract_from_repo(fake_entry)
        if extraction["tools_count"] == 0:
            continue
        sub_name = sub_root.split("/", 1)[1]
        out.append({
            "name": sub_name,
            "subpath": sub_root,
            "tools_count": extraction["tools_count"],
            "tools": extraction["tools"],
            "extraction_method": extraction["extraction_method"],
        })
    return out


def summarize_for_index(extraction: dict) -> dict[str, Any]:
    """Compact view embeddable in index.json / per-server JSON.
    Just the count + first few tool names — full list lives in data/tools/."""
    tools = extraction.get("tools") or []
    return {
        "tool_count": extraction.get("tools_count", 0),
        "tool_names_preview": [t["name"] for t in tools[:10]],
        "extraction_method": extraction.get("extraction_method", "none"),
        "extraction_confidence": extraction.get("extraction_confidence", 0.0),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=".cache", help="dir of cached repo JSONs")
    ap.add_argument("--out", default="data", help="output dir; tools/ subdir created")
    args = ap.parse_args()

    cache_dir = Path(args.cache)
    out_dir = Path(args.out) / "tools"
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    total_tools = 0
    for f in sorted(cache_dir.glob("*.json")):
        try:
            entry = json.loads(f.read_text())
        except Exception as e:
            print(f"  skip {f.name}: {e}", file=sys.stderr)
            continue
        extraction = extract_from_repo(entry)
        if not extraction["source_files_scanned"]:
            continue  # nothing to extract from
        slug = extraction["slug"]
        (out_dir / f"{slug}.json").write_text(json.dumps(extraction, ensure_ascii=False, indent=2))
        written += 1
        total_tools += extraction["tools_count"]

    print(f"extractor: wrote {written} files, {total_tools} tools total → {out_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
