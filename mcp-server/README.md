# @mcprated/mcp-server (planned)

Agent-first MCP server distributed as an npm package. Runs locally via stdio,
fetches data from the public MCPRated static API.

**Status:** placeholder. Implementation arrives in v2.x roadmap.

## Planned tools

```
mcprated.search(query, limit?)        Search the catalog by intent
mcprated.get(repo)                    Fetch full lint details for one repo
mcprated.recommend(intent)            Top servers for a use case
mcprated.compare(repo_a, repo_b)      Side-by-side
mcprated.top(axis, limit?)            Leaderboard per axis
mcprated.watchlist(repos[])           Local subscription, alert on grade changes
```

## Planned install

```json
{
  "mcpServers": {
    "mcprated": {
      "command": "npx",
      "args": ["-y", "@mcprated/mcp-server"]
    }
  }
}
```

The server fetches from `https://mcprated.dev/api/v1/*.json` (static, CDN-cached, free).
No service to host on our side — pure client-side agent helper.
