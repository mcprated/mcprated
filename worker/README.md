# mcprated-mcp-worker

Cloudflare Worker that exposes the MCPRated catalog as an MCP Streamable HTTP server.

**Live:** https://mcp.mcprated.workers.dev

## Architecture

Thin proxy. The Worker speaks JSON-RPC 2.0 over POST and proxies tool calls to the static JSON shards under `https://mcprated.github.io/mcprated/api/v1/`. Per-edge Cache API gives 1h TTL on outbound fetches; behind it the gh-pages CDN does its own caching.

No state, no Durable Objects, no KV. Free tier with generous headroom.

## Tools

| Tool | Backed by | Purpose |
|---|---|---|
| `find_server` | `/api/v1/by-capability/<cap>.json` | Find servers tagged with a capability |
| `vet` | `/api/v1/vet/<slug>.json` | Trust verdict for one server |
| `alternatives` | `/api/v1/alternatives/<slug>.json` | Capability-similar fallbacks |
| `by_kind` | `/api/v1/by-kind/<kind>.json` | Filter by classifier (server/client/...) |
| `top` | `/api/v1/top.json` | Top by composite/stars/recency |
| `server_detail` | `/servers/<slug>.json` | Full lint output incl. signal pass/fail |

## Local development

```bash
npm install
npm run dev          # starts on localhost:8787
```

Test with the official MCP Inspector:

```bash
npx @modelcontextprotocol/inspector@latest http://localhost:8787
```

Or raw curl:

```bash
curl -X POST http://localhost:8787 \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Deploy

Auto-deploys on push to `main` when files in `worker/` change. See `.github/workflows/deploy-worker.yml`.

Manual deploy from local:

```bash
source ../.local/cf-secrets.env   # provides CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID
npm run deploy
```

## Adding to a client

Claude Code, Cursor, Cline, Continue, etc. — all support remote MCP via streamable HTTP:

```bash
claude mcp add --transport http mcprated https://mcp.mcprated.workers.dev
```

## Files

- `wrangler.toml` — Worker config (name=`mcp`, vars, future custom domain stub)
- `src/index.ts` — full Worker implementation, ~330 LOC, no runtime deps
- `package.json` — wrangler + typescript dev deps only
- `tsconfig.json` — strict TS targeting ES2022
