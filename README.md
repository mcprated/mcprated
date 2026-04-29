# MCPRated

**Agent-readable index of every MCP server. Built for LLMs to discover, vet, and choose tools at runtime — not for humans to browse.**

Open ruleset, daily-updated, deterministic. Static catalog + remote MCP endpoint, both live.

**🌐 Live**
- MCP server: `https://mcp.mcprated.workers.dev` (streamable HTTP)
- Static catalog: [mcprated.github.io/mcprated](https://mcprated.github.io/mcprated/)

## Add to your client in one line

**Claude Code / Claude Desktop:**

```bash
claude mcp add --transport http mcprated https://mcp.mcprated.workers.dev
```

**Cursor / Cline / Continue / any client supporting remote MCP:** paste into your config:

```json
{"mcpServers": {"mcprated": {"url": "https://mcp.mcprated.workers.dev"}}}
```

The agent then has access to **8 tools**:

| Tool | When to call |
|---|---|
| `find_server` | Map your need to a capability category (12 of them) and rank servers by quality |
| `search` | Free-text search when the capability enum doesn't fit |
| `find_tool` | Discover a specific tool by name (`browser_navigate`, `read_file`, …) across all servers |
| `vet` | Trust verdict for one server (verified / caution / low_quality) before installing |
| `alternatives` | Capability-similar fallbacks when a server is unavailable |
| `by_kind` | Filter classifier output (server / client / framework / tool / ambiguous) |
| `top` | Top servers by composite, stars, or recency |
| `server_detail` | Full lint signal breakdown — every signal, every reason |

See `https://mcp.mcprated.workers.dev` for a live tool list, or [`/api/v1/manifest.json`](https://mcprated.github.io/mcprated/api/v1/manifest.json) for the JSON schema.

## Static catalog API

Fallback for agents without remote-MCP support, or for direct integration without an MCP client. No auth, stable URLs, daily refresh.

```bash
curl https://mcprated.github.io/mcprated/llms.txt                            # discovery + endpoint map
curl https://mcprated.github.io/mcprated/api/v1/manifest.json                # full endpoint schema
curl https://mcprated.github.io/mcprated/api/v1/by-capability/database.json  # one shard per category
curl https://mcprated.github.io/mcprated/api/v1/vet/<owner>__<repo>.json     # trust subset
curl https://mcprated.github.io/mcprated/api/v1/tools-index.json             # flat list of every extracted tool
curl https://mcprated.github.io/mcprated/index.json                          # full catalog
curl https://mcprated.github.io/mcprated/servers/<owner>__<repo>.json        # per-server detail
curl https://mcprated.github.io/mcprated/excluded.json                       # transparency
```

Per server we publish: composite score, four axis scores, `kind` (server / client / framework / tool / ambiguous), `subkind` (integration / aggregator / prompt-tool / agent-product), `capabilities[]`, `distribution`, `tool_count`, `tool_names_preview`, hard flags, license, language, recency.

Daily snapshots in [Releases](https://github.com/mcprated/mcprated/releases) — historical state retained.

## Run locally (for development)

```bash
# In one terminal — local Worker
cd worker
npm install
npm run dev      # starts MCP server on http://localhost:8787

# In another terminal — connect a client
claude mcp add --transport http mcprated-local http://localhost:8787

# Or test interactively with the official MCP Inspector
npx @modelcontextprotocol/inspector@latest http://localhost:8787
```

The local Worker uses the same source as production. Test changes locally; auto-deploy fires on push to `main` (gated by 260+ tests).

## Smoke harness — see what your change did, before push

After every scoring/extractor change, run the local smoke harness. It lints every entry in `tests/regression/seed.txt` and prints a diff against the last snapshot — no judgment, just data.

```bash
python3 linter/smoke.py            # first run — snapshot only
# ... make changes to linter/ ...
python3 linter/smoke.py            # second run — diff vs last snapshot
```

Output: a current-state table (composite, kind, capabilities, tool_count, hard_flags per server) and a diff section listing only what changed. Last 10 snapshots are kept under `.local/smoke/`.

Use cases:
- Verify a taxonomy keyword change didn't shift unrelated capabilities
- Confirm an extractor patch raises tool_count for the targeted servers
- Catch trust-axis regressions when adding/removing signals
- Check the Tier B junk repos still score low

The script reuses the shared `.cache/` so it's fast (~30s after warm cache). Add `GITHUB_TOKEN=$(gh auth token)` to fetch missing entries authenticated.

## What we catalog

An **MCP server** is a runnable artifact implementing the Model Context Protocol (stdio / SSE / streamable HTTP) that exposes ≥1 of `tools` / `resources` / `prompts` and is distributed as a product for use by an MCP client. We do **not** catalog frameworks *for building* MCP servers (FastMCP, official SDKs), MCP clients/inspectors, or end-user apps that consume MCP without exposing it.

See [methodology.md](methodology.md) for the full operational definition and [linter/taxonomy/v1.yaml](linter/taxonomy/v1.yaml) for the capability vocabulary.

Score model: 4 axes × 0–100 → composite 0–100. Hard flags can cap composite (`archived` → 30, `empty_description` → 75, …).

| Axis | Question |
|---|---|
| Reliability | Will it work and keep working? |
| Documentation | Can a stranger figure this out? |
| Trust | Safe to depend on? |
| Community | Are people caring for it? |

Open ruleset (MIT) at [linter/rules/v1.0/](linter/rules/v1.0/). Open data (CC-BY-4.0). Versioned: every score carries `rule_set_version`.

## For maintainers — embed your badge

```markdown
[![MCPRated](https://mcprated.github.io/mcprated/badges/<owner>__<repo>.svg)](https://mcprated.github.io/mcprated/)
```

Replace `<owner>__<repo>` with double-underscore-encoded path. Example:

```markdown
[![MCPRated](https://mcprated.github.io/mcprated/badges/microsoft__playwright-mcp.svg)](https://mcprated.github.io/mcprated/)
```

Renders as: ![MCPRated](https://mcprated.github.io/mcprated/badges/microsoft__playwright-mcp.svg)

Badge always reflects the latest score. No URL pinning, no stale embeds.

## Status

**v0.2 — agent-first core.** Reference seed ~25 servers + topic-search crawl ~125 indexed. Daily lint running. `kind` + `capabilities` shipped in rule_set v1.1. Coming next: agent-shaped endpoints (`/api/v1/find`, `/vet`, `/by-capability/<cap>`) and `@mcprated/mcp-server` as an installable npm package.

## Run lint locally

```bash
git clone https://github.com/mcprated/mcprated && cd mcprated
export GITHUB_TOKEN=ghp_...                                # 5000/h authed
python linter/crawler.py --seed tests/regression/seed.txt
python linter/lint.py
```

## Docs

- [methodology.md](methodology.md) — score model, hard flags, what counts as an MCP server, versioning policy
- [linter/rules/v1.0/](linter/rules/v1.0/) — open YAML ruleset (4 files, 20 signals)
- [linter/taxonomy/v1.yaml](linter/taxonomy/v1.yaml) — capability vocabulary (12 categories)
- [CHANGELOG.md](CHANGELOG.md) — rule-set version history

## License

MIT (code) · CC-BY-4.0 (data in `data/` and release snapshots) · See [LICENSE](LICENSE), [DATA-LICENSE](DATA-LICENSE)
