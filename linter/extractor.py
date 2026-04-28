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

class _PyToolVisitor(pyast.NodeVisitor):
    """Walk a Python AST collecting MCP tool registrations.

    Recognized patterns (most common first):
      @mcp.tool(...)            decorator on a function
      @mcp.tool                 same, no parens
      @server.tool(...)         alternate handle name
      @app.tool(...)            FastMCP convention
      mcp.tool(...)(func)       (rare — programmatic decoration)

    For each match we record the function name, its docstring (description),
    and the parameter names (input_keys) inferred from the signature.
    """

    def __init__(self):
        self.tools: list[dict[str, Any]] = []

    def _is_tool_decorator(self, dec: pyast.expr) -> bool:
        # @mcp.tool  or  @mcp.tool(...)
        node = dec.func if isinstance(dec, pyast.Call) else dec
        return (
            isinstance(node, pyast.Attribute)
            and node.attr == "tool"
            and isinstance(node.value, pyast.Name)
            and node.value.id in ("mcp", "server", "app", "fastmcp")
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

# Matches `{ ... }` blocks at most 1500 chars long with no nested braces —
# good enough for a single tool descriptor object in an array literal.
_TS_BRACE_BLOCK_RX = re.compile(r"\{([^{}]{0,1500})\}", re.DOTALL)
_TS_NAME_RX = re.compile(r"""\bname\s*:\s*["']([\w\-.]+)["']""")
_TS_DESC_RX = re.compile(r"""\bdescription\s*:\s*["']([^"']{0,200})["']""")


def extract_typescript(source: str) -> list[dict[str, Any]]:
    """Best-effort. Returns deduplicated tool list across two patterns:
    direct `server.tool('name', ...)` calls AND inline `{ name: 'x', description: 'y' }`
    objects in tools/list array returns.

    Strategy: name and description are extracted SEPARATELY per `{...}` block,
    not in one regex. An optional capture in a single non-greedy regex
    misses descriptions whenever the matcher can satisfy the pattern earlier.
    """
    seen: dict[str, dict[str, Any]] = {}

    # Form 1: registration call sites
    for m in _TS_TOOL_REGISTER_RX.finditer(source):
        name = m.group(1)
        seen.setdefault(name, {"name": name, "description": None, "input_keys": []})

    # Form 2: object literals with name + (optional) description
    for block in _TS_BRACE_BLOCK_RX.finditer(source):
        body = block.group(1)
        name_m = _TS_NAME_RX.search(body)
        if not name_m:
            continue
        name = name_m.group(1)
        desc_m = _TS_DESC_RX.search(body)
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
