# MCPRated

**Agent-readable index of every MCP server. Built for LLMs to discover, vet, and choose tools at runtime — not for humans to browse.**

Open ruleset, daily-updated, deterministic. Trust scores today; capability index and `@mcprated/mcp-server` next.

**🌐 Live: [mcprated.github.io/mcprated](https://mcprated.github.io/mcprated/)**

## For agents

Static JSON, no auth, stable URLs, daily refresh. Hit these from your system prompt or runtime.

```bash
curl https://mcprated.github.io/mcprated/llms.txt                            # discovery + endpoint map
curl https://mcprated.github.io/mcprated/index.json                          # full catalog
curl https://mcprated.github.io/mcprated/servers/<owner>__<repo>.json        # per-server detail
curl https://mcprated.github.io/mcprated/excluded.json                       # transparency: what we filtered out and why
```

Per server we publish: composite score, four axis scores, `kind` (server / client / framework / tool / ambiguous), `subkind` (integration / aggregator / prompt-tool / agent-product), `capabilities[]` (taxonomy v1: database, web, search, devtools, comms, …), `distribution`, hard flags, license, language, recency.

Daily snapshots in [Releases](https://github.com/mcprated/mcprated/releases) — historical state retained.

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
