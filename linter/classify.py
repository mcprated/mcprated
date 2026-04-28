#!/usr/bin/env python3
"""MCPRated classifier — kind + capabilities (rule_set v1.1).

Two pure functions:
  classify_kind(repo_data)           -> (kind, subkind, confidence, reason)
  classify_capabilities(repo_data)   -> sorted list[str]  (top 3 max)

Operational definition of MCP server (v1.1):
  Runnable artifact implementing MCP protocol (stdio/SSE/HTTP) that exposes
  >=1 of tools/resources/prompts and is distributed as a product for use by
  an MCP client.
  NOT: frameworks FOR BUILDING MCP servers (FastMCP, official SDKs),
       MCP clients/inspectors, end-user apps that consume MCP without
       exposing it, standalone CLIs that don't implement MCP.

`kind` values:    server | client | framework | tool | ambiguous
`subkind` values (only for kind=server):
    integration   - default; bridges to external system
    aggregator    - gateway to thousands of sub-tools (Zapier, Pipedream)
    prompt-tool   - in-context reasoning aid, no external capability
                    (sequential-thinking, dice-roller)
    agent-product - a product whose MCP surface is one of several
                    (serena, task-master, awslabs/mcp suite)

Stdlib only.
"""
from __future__ import annotations
import re

# Capability taxonomy v1.0 — mirror of linter/taxonomy/v1.yaml.
# YAML file is the human-readable source; this dict is what runs.
# Bump TAXONOMY_VERSION when keywords change.
#
# Layer 1 fix #5: keywords are matched as whole words (regex \b boundary)
# to kill false positives like " git " in "github" or " image " in
# "image search results". Multi-word keywords match as phrases verbatim.
TAXONOMY_VERSION = "1.0"

_TAXONOMY: dict[str, list[str]] = {
    "database":     ["postgres", "postgresql", "mysql", "sqlite", "mongodb", "mongo",
                     "redis", "neo4j", "sql", "duckdb", "supabase", "firestore",
                     "dynamodb", "clickhouse", "bigquery", "snowflake",
                     "database", "rdbms"],
    "filesystem":   ["filesystem", "file system", "read files", "write files",
                     "local files", "directory access", "file operations"],
    "web":          ["browser", "web scraping", "playwright", "puppeteer",
                     "fetch url", "http client", "web automation", "page snapshot",
                     "headless browser", "browser automation", "chromium"],
    "search":       ["full-text search", "vector search", "semantic search",
                     "search engine", "retrieval", "embeddings index",
                     "elasticsearch", "search api", "rag"],
    "productivity": ["notion", "todoist", "linear app", "asana", "jira",
                     "google calendar", "gmail", "outlook", "google docs",
                     "google sheets", "confluence", "airtable", "monday.com"],
    "comms":        ["slack", "discord", "telegram", "whatsapp", "twilio",
                     "email", "smtp", "imap", "matrix protocol", "mattermost",
                     "send message", "messaging"],
    "devtools":     ["github", "gitlab", "bitbucket", "sentry", "datadog",
                     "ci/cd", "docker", "kubernetes", "terraform", "ansible",
                     "deployment", "code review", "git operations"],
    "cloud":        ["aws", "gcp", "azure", "cloudflare", "vercel", "netlify",
                     "fly.io", "heroku", "google cloud", "lambda", "s3",
                     "cloudflare workers"],
    "ai":           ["openai", "anthropic", "llm", "embeddings", "image generation",
                     "transcription", "whisper", "stable diffusion", "replicate",
                     "huggingface", "gemini api"],
    "memory":       ["knowledge graph", "memory store", "notes app", "journal",
                     "vault", "obsidian", "second brain", "personal knowledge",
                     "anki", "long-term memory"],
    "finance":      ["stripe", "plaid", "payments", "blockchain", "ethereum",
                     "bitcoin", "defi", "trading api", "coinbase", "banking api"],
    "media":        ["ffmpeg", "ocr", "image processing", "video editing",
                     "speech to text", "audio processing", "video processing"],
}

# Pre-compile word-boundary regexes once. Multi-word phrases match as-is
# (with whitespace tolerance); single tokens get \b boundaries.
def _compile_taxonomy(taxonomy: dict[str, list[str]]) -> dict[str, list[re.Pattern]]:
    out: dict[str, list[re.Pattern]] = {}
    for cat, kws in taxonomy.items():
        patterns = []
        for kw in kws:
            if " " in kw or "/" in kw or "." in kw:
                # Multi-word or punctuated: literal match with flexible whitespace
                patterns.append(re.compile(re.escape(kw), re.I))
            else:
                # Single token: word-boundary
                patterns.append(re.compile(rf"\b{re.escape(kw)}\b", re.I))
        out[cat] = patterns
    return out


_TAXONOMY_RX = _compile_taxonomy(_TAXONOMY)

# ---------------------------------------------------------------------------
# kind classification
# ---------------------------------------------------------------------------

# Negative signals — repo claims to be MCP but is actually a different kind.
#
# Phrases must be specific enough that they only fire when the repo is asserting
# its OWN identity as framework/client/tool — not when it merely mentions one
# in install instructions ("Add to your MCP client config" appears in every
# server README). All phrases below are pinned to first-person framings.
_FRAMEWORK_PHRASES = (
    "framework for building mcp",
    "library for building mcp",
    "build your own mcp server",
    "library for creating mcp",
    "sdk for the model context protocol",
    "the official mcp sdk",
    "python sdk for the model context protocol",
    "typescript sdk for the model context protocol",
)

_CLIENT_PHRASES = (
    "is an mcp client", "is a mcp client", "this is an mcp client",
    "mcp client implementation", "client implementation of mcp",
    "is an mcp host", "is a mcp host", "is an mcp gateway",
    "is an mcp proxy", "is a mcp proxy",
    "this client connects to mcp servers",
    "desktop client for mcp",
)

_TOOL_PHRASES = (
    "inspector for mcp servers", "debugger for mcp servers",
    "test harness for mcp", "developer tool for mcp",
)

_INSPECTOR_NAMES = ("inspector", "devtools-mcp", "mcp-devtools")
_CLIENT_NAME_TOKENS = ("-mcp-client", "mcp-client-", "-mcp-host", "-mcp-proxy",
                      "-mcp-gui", "-mcp-ui")

# Positive server signals — strong evidence repo IS a server.
_SERVER_RUN_PATTERNS = (
    re.compile(r"\bnew\s+Server\s*\(", re.I),                # @modelcontextprotocol/sdk
    re.compile(r"\bFastMCP\s*\(", re.I),                     # python FastMCP server
    re.compile(r"@mcp\.tool\b"),                             # python decorator
    re.compile(r"\bmcp\.server\.fastmcp\b", re.I),
    re.compile(r"\bsetRequestHandler\s*\(\s*['\"]tools/list", re.I),
    re.compile(r"\bsetRequestHandler\s*\(\s*['\"]resources/list", re.I),
    re.compile(r"\bserver\.tool\s*\(", re.I),
    re.compile(r"\bserver\.resource\s*\(", re.I),
    re.compile(r"\bserver\.prompt\s*\(", re.I),
)

# Aggregator / prompt-tool subkind hints
_AGGREGATOR_PHRASES = (
    "thousands of integrations", "5000+ apps", "one mcp for every", "universal mcp",
    "gateway to", "aggregates multiple", "zapier mcp", "pipedream mcp",
)
_PROMPT_TOOL_NAMES = (
    "sequential-thinking", "sequentialthinking", "dice-roller", "dice_roller",
    "scratchpad", "thought-process",
)
_PROMPT_TOOL_PHRASES = (
    "chain-of-thought tool", "scratchpad for reasoning",
    "in-context reasoning", "no external integration",
)


def _haystack(d: dict) -> str:
    """Lowercased blob: description + topics + first 2KB of README."""
    repo = d.get("repo", {})
    desc = (repo.get("description") or "").lower()
    topics = " ".join(repo.get("topics", []) if isinstance(repo, dict) else []).lower()
    readme = (d.get("readme") or "")[:2000].lower()
    return f"{desc}\n{topics}\n{readme}"


def _name(d: dict) -> str:
    return (d.get("repo", {}).get("name") or "").lower()


def _full_name(d: dict) -> str:
    repo = d.get("repo", {})
    owner = (repo.get("owner") or {}).get("login") or repo.get("full_name", "?").split("/")[0]
    return f"{owner}/{repo.get('name', '?')}".lower()


def _has_run_pattern(d: dict) -> bool:
    """Look for server-run pattern in any cached source file."""
    files = d.get("source_files") or {}
    if not isinstance(files, dict):
        return False
    for content in files.values():
        if not isinstance(content, str):
            continue
        for pat in _SERVER_RUN_PATTERNS:
            if pat.search(content):
                return True
    return False


_SDK_DEP_HINTS = (
    "@modelcontextprotocol/",          # npm
    "modelcontextprotocol-sdk",         # PyPI normalized
    '"mcp"', "'mcp'",                   # exact py dep token, table style
    '"mcp==', "'mcp==",                 # PEP 621 list-style: "mcp==1.0"
    '"mcp>=', "'mcp>=", '"mcp~=', "'mcp~=", '"mcp<', "'mcp<',",
    "\nmcp ", "\nmcp==", "\nmcp>=", "\nmcp~=",  # bare requirements.txt style
    "\nmcp =",                          # poetry table: mcp = "^1.0"
    "github.com/modelcontextprotocol/go-sdk",
    "github.com/mark3labs/mcp-go",
    "mcp-go",
    "rmcp", "mcp-rs", "mcp-sdk",
)


def _has_sdk_dep(d: dict) -> bool:
    """Detects MCP SDK dependency across npm / PyPI / Go / Cargo / Poetry / PEP 621.

    Layer 1 fix #4: original regex missed Python list-style and Go imports.
    Now also scans source_files for Go imports of mcp-go (they don't go in go.mod
    when a repo vendors them or uses them indirectly).
    """
    pkg_blob = "\n" + "\n".join((d.get("pkg") or {}).values()).lower()
    for hint in _SDK_DEP_HINTS:
        if hint.lower() in pkg_blob:
            return True
    # Go: SDK is referenced via import in source, not always pinned in go.mod.
    src_blob = "\n".join((d.get("source_files") or {}).values()).lower()
    if 'github.com/modelcontextprotocol/go-sdk' in src_blob:
        return True
    if 'github.com/mark3labs/mcp-go' in src_blob:
        return True
    return False


def _name_matches_mcp(name: str) -> bool:
    """Layer 1 fix #2: widen name pattern. Original missed *-mcp-server, *-mcp-*."""
    if name == "mcp":
        return True
    if name.startswith("mcp-") or name.endswith("-mcp"):
        return True
    # any segment-bounded mcp token: foo-mcp-bar, foo-mcp_bar, mcp_server, etc.
    if "-mcp-" in name or "_mcp_" in name or "-mcp_" in name or "_mcp-" in name:
        return True
    if name.endswith("-mcp-server") or name.endswith("_mcp_server"):
        return True
    return False


def classify_kind(d: dict) -> tuple[str, str, float, str]:
    """Return (kind, subkind, confidence, reason).

    kind ∈ {server, client, framework, tool, ambiguous}
    subkind ∈ {integration, aggregator, prompt-tool, agent-product, ""}  (server only)
    confidence ∈ [0, 1]

    Decision order is deliberate. Server-run pattern in actual source code
    (Layer 2) wins over everything because it's the only definitive evidence
    that this artifact IS a server. Fallbacks then walk down the cliff of
    increasing ambiguity: pinned SDK dep → mcpServers config → name pattern.
    """
    hay = _haystack(d)
    name = _name(d)
    full = _full_name(d)
    has_sdk_dep = _has_sdk_dep(d)
    has_run_pattern = _has_run_pattern(d)

    # Layer 2 — strongest signal: server-run pattern in source code.
    # If it runs as a server, it IS a server, full stop. Beats every
    # negative-signal phrase in README (which often contains install hints
    # like "this works with any MCP client" that confuse phrase matching).
    if has_run_pattern:
        subkind, sub_reason = _server_subkind(hay, name)
        return "server", subkind, 0.95, f"server-run pattern in source ({sub_reason})"

    # Anthropic-owned SDK repos — explicit allowlist, beats everything else.
    if full in ("modelcontextprotocol/python-sdk", "modelcontextprotocol/typescript-sdk",
                "modelcontextprotocol/csharp-sdk", "modelcontextprotocol/kotlin-sdk",
                "modelcontextprotocol/java-sdk", "modelcontextprotocol/swift-sdk",
                "modelcontextprotocol/rust-sdk", "modelcontextprotocol/go-sdk"):
        return "framework", "", 1.0, "official MCP SDK repo"

    # Known multi-server suite repos — root has no pkg/source for one server,
    # but the whole repo IS the catalog of servers. Treat as server/agent-product
    # until v1.2 adds sub-server listings.
    if full in ("awslabs/mcp", "modelcontextprotocol/servers",
                "googleapis/genai-toolbox", "googleapis/mcp-toolbox"):
        return "server", "agent-product", 1.0, "known multi-server suite repo"

    # Framework detection (Layer 1 fix #3): only if NO SDK dep present.
    # A repo that depends on the MCP SDK is consuming it, not being it.
    if not has_sdk_dep:
        for phrase in _FRAMEWORK_PHRASES:
            if phrase in hay:
                return "framework", "", 0.9, f"framework phrase: '{phrase}'"
        if name in ("fastmcp", "mcp", "mcp-python", "mcp-typescript", "modelcontextprotocol"):
            return "framework", "", 0.85, f"framework name: {name}"

    # Tool / inspector detection — name token (very specific) + tightened phrases.
    for token in _INSPECTOR_NAMES:
        if token in name:
            return "tool", "", 0.85, f"inspector/devtool name token: {token}"
    for phrase in _TOOL_PHRASES:
        if phrase in hay:
            return "tool", "", 0.8, f"tool phrase: '{phrase}'"

    # Client detection (Layer 1 fix #1): tightened phrases require first-person
    # identity ("is an mcp client"), no longer matches incidental mentions.
    # AND if SDK dep is present, this is almost certainly a server even if the
    # README mentions "client" — clients don't depend on the server SDK.
    if not has_sdk_dep:
        for phrase in _CLIENT_PHRASES:
            if phrase in hay:
                return "client", "", 0.8, f"client phrase: '{phrase}'"
        for token in _CLIENT_NAME_TOKENS:
            if token in name:
                return "client", "", 0.7, f"client name token: {token}"

    # Server detection — fallback hierarchy.
    if has_sdk_dep:
        subkind, sub_reason = _server_subkind(hay, name)
        return "server", subkind, 0.7, f"sdk dep in package metadata ({sub_reason})"

    has_config = '"mcpservers"' in (d.get("readme") or "").lower()
    if has_config:
        subkind, sub_reason = _server_subkind(hay, name)
        return "server", subkind, 0.55, f"mcpServers config in README ({sub_reason})"

    # Last-resort: name pattern (widened in Layer 1 fix #2).
    if _name_matches_mcp(name):
        subkind, sub_reason = _server_subkind(hay, name)
        return "server", subkind, 0.45, f"name pattern: {name} ({sub_reason})"

    return "ambiguous", "", 0.3, "no decisive kind signal"


def _server_subkind(hay: str, name: str) -> tuple[str, str]:
    """Determine subkind for a kind=server. Returns (subkind, reason)."""
    for tok in _PROMPT_TOOL_NAMES:
        if tok in name:
            return "prompt-tool", f"prompt-tool name: {tok}"
    for phrase in _PROMPT_TOOL_PHRASES:
        if phrase in hay:
            return "prompt-tool", f"prompt-tool phrase: '{phrase}'"
    for phrase in _AGGREGATOR_PHRASES:
        if phrase in hay:
            return "aggregator", f"aggregator phrase: '{phrase}'"
    return "integration", "default"


# ---------------------------------------------------------------------------
# capability classification
# ---------------------------------------------------------------------------

def classify_capabilities(d: dict, top_n: int = 3) -> list[str]:
    """Return up to top_n capability tags ranked by keyword hit count.

    Empty list if no keyword matches; agent-side this is surfaced as
    `capability=unknown` rather than being treated as missing data.

    Word-boundary aware (Layer 1 fix #5) so "git" no longer matches "github"
    and "image" no longer matches "image search" inside another category's
    description.
    """
    hay = _haystack(d)
    if not hay.strip():
        return []
    scores: dict[str, int] = {}
    for cat, patterns in _TAXONOMY_RX.items():
        hits = sum(1 for p in patterns if p.search(hay))
        if hits:
            scores[cat] = hits
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [cat for cat, _ in ranked[:top_n]]
