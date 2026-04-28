/**
 * mcprated-mcp — Cloudflare Worker that wraps the MCPRated catalog as
 * MCP Streamable HTTP.
 *
 * Architecture: thin proxy over static JSON shards on gh-pages. No state,
 * no Durable Objects, no KV. Per-edge Cache API gives 1h TTL on outbound
 * fetches; behind it our gh-pages CDN does its own caching.
 *
 * Protocol: implements just enough of MCP (initialize, tools/list, tools/call)
 * to satisfy mainstream clients (Claude Code, Cursor, Cline). No SDK; the
 * surface is small enough that direct JSON-RPC handling is clearer than
 * pulling in @modelcontextprotocol/sdk and its transport adapters.
 */

interface Env {
  CATALOG_BASE: string;
  SERVER_VERSION: string;
}

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: number | string | null;
  method: string;
  params?: any;
}

const PROTOCOL_VERSION = "2024-11-05";

// Tool definitions — kept in sync with /api/v1/manifest.json `mcp_tools` so a
// cold agent that fetched the manifest first sees the same surface here.
const TOOLS = [
  {
    name: "find_server",
    description:
      "Find MCP servers tagged with a capability. Returns ranked list (top by composite score). Use this when an agent needs an MCP server for a specific category like database, web, search, devtools.",
    inputSchema: {
      type: "object",
      properties: {
        capability: {
          type: "string",
          enum: [
            "database", "filesystem", "web", "search", "productivity",
            "comms", "devtools", "cloud", "ai", "memory", "finance", "media",
            "unknown",
          ],
          description: "Capability tag to filter by (taxonomy v1.0).",
        },
        limit: {
          type: "integer",
          default: 10,
          minimum: 1,
          maximum: 50,
          description: "Max servers to return.",
        },
      },
      required: ["capability"],
    },
  },
  {
    name: "vet",
    description:
      "Trust-focused summary of one MCP server: composite score, four axis scores, license, hard flags, plus a derived verdict (verified | caution | low_quality). Use before recommending a server for production.",
    inputSchema: {
      type: "object",
      properties: {
        slug: {
          type: "string",
          description:
            "Server identifier as <owner>__<repo> (e.g. microsoft__playwright-mcp).",
        },
      },
      required: ["slug"],
    },
  },
  {
    name: "alternatives",
    description:
      "Find MCP servers with overlapping capabilities to a given one. Useful for fallback when a primary choice is unavailable, or for comparison.",
    inputSchema: {
      type: "object",
      properties: {
        slug: {
          type: "string",
          description: "<owner>__<repo>",
        },
      },
      required: ["slug"],
    },
  },
  {
    name: "by_kind",
    description:
      "List entries by classifier kind. server | client | framework | tool | ambiguous. The default catalog ranking shows kind=server; use this to inspect classifier output for the other kinds.",
    inputSchema: {
      type: "object",
      properties: {
        kind: {
          type: "string",
          enum: ["server", "client", "framework", "tool", "ambiguous"],
        },
      },
      required: ["kind"],
    },
  },
  {
    name: "top",
    description:
      "Top MCP servers by ranking. Three orderings: composite score (quality), stars (popularity), recency (last push).",
    inputSchema: {
      type: "object",
      properties: {
        ranking: {
          type: "string",
          enum: ["composite", "stars", "recency"],
          default: "composite",
        },
        limit: {
          type: "integer",
          default: 10,
          minimum: 1,
          maximum: 25,
        },
      },
    },
  },
  {
    name: "server_detail",
    description:
      "Full lint output for one MCP server: every signal pass/fail with reason, all four axes, hard flags. Use when an agent needs evidence-level detail beyond the trust verdict.",
    inputSchema: {
      type: "object",
      properties: {
        slug: { type: "string", description: "<owner>__<repo>" },
      },
      required: ["slug"],
    },
  },
];

// ---------------------------------------------------------------------------
// HTTP / cache helpers
// ---------------------------------------------------------------------------

// Bumped per-deploy to bust any stale CF colo cache entries (e.g. when an
// earlier deploy accidentally pinned a 404). Increment when redeploying after
// changing fetch semantics.
const CATALOG_CACHE_VERSION = "2";

async function fetchCatalog(
  env: Env,
  ctx: ExecutionContext,
  path: string
): Promise<any> {
  const url = `${env.CATALOG_BASE}${path}?_v=${CATALOG_CACHE_VERSION}`;
  const cache = caches.default;
  const cacheKey = new Request(url, { method: "GET" });

  // Workers Cache API is the ONLY layer we control. CF colo cache is left to
  // honour origin Cache-Control headers from gh-pages — no cf hints here, so
  // a transient 404 can't pin itself.
  let cached = await cache.match(cacheKey);
  if (cached) {
    return cached.json();
  }

  const upstream = await fetch(url);
  if (!upstream.ok) {
    throw new Error(`upstream ${upstream.status}: ${url}`);
  }

  const body = await upstream.text();
  const cacheable = new Response(body, {
    status: 200,
    headers: {
      "content-type": "application/json",
      "cache-control": "public, max-age=3600",
    },
  });
  ctx.waitUntil(cache.put(cacheKey, cacheable.clone()));
  return JSON.parse(body);
}

// ---------------------------------------------------------------------------
// Tool implementations — each is a passthrough to one /api/v1/* shard.
// Returns MCP `content` envelope. JSON.stringify keeps the response shape
// simple; callers parse as needed.
// ---------------------------------------------------------------------------

async function callTool(
  env: Env,
  ctx: ExecutionContext,
  name: string,
  args: any
): Promise<any> {
  const a = args ?? {};

  switch (name) {
    case "find_server": {
      const cap = String(a.capability ?? "").trim();
      const limit = Math.max(1, Math.min(50, Number(a.limit ?? 10)));
      if (!cap) throw new Error("missing 'capability'");
      const data = await fetchCatalog(env, ctx, `/api/v1/by-capability/${cap}.json`);
      const servers = (data.servers ?? []).slice(0, limit);
      return contentEnvelope({
        capability: cap,
        total_matches: data.count,
        returned: servers.length,
        servers,
      });
    }

    case "vet": {
      const slug = String(a.slug ?? "").trim();
      if (!slug) throw new Error("missing 'slug'");
      const data = await fetchCatalog(env, ctx, `/api/v1/vet/${slug}.json`);
      return contentEnvelope(data);
    }

    case "alternatives": {
      const slug = String(a.slug ?? "").trim();
      if (!slug) throw new Error("missing 'slug'");
      const data = await fetchCatalog(env, ctx, `/api/v1/alternatives/${slug}.json`);
      return contentEnvelope(data);
    }

    case "by_kind": {
      const kind = String(a.kind ?? "").trim();
      if (!kind) throw new Error("missing 'kind'");
      const data = await fetchCatalog(env, ctx, `/api/v1/by-kind/${kind}.json`);
      return contentEnvelope(data);
    }

    case "top": {
      const ranking = String(a.ranking ?? "composite");
      const limit = Math.max(1, Math.min(25, Number(a.limit ?? 10)));
      const data = await fetchCatalog(env, ctx, `/api/v1/top.json`);
      const key =
        ranking === "stars" ? "by_stars"
        : ranking === "recency" ? "by_recency"
        : "by_composite";
      const servers = (data[key] ?? []).slice(0, limit);
      return contentEnvelope({
        ranking,
        returned: servers.length,
        servers,
      });
    }

    case "server_detail": {
      const slug = String(a.slug ?? "").trim();
      if (!slug) throw new Error("missing 'slug'");
      const data = await fetchCatalog(env, ctx, `/servers/${slug}.json`);
      return contentEnvelope(data);
    }

    default:
      throw new Error(`unknown tool: ${name}`);
  }
}

function contentEnvelope(payload: unknown) {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(payload, null, 2),
      },
    ],
  };
}

// ---------------------------------------------------------------------------
// JSON-RPC handler
// ---------------------------------------------------------------------------

function rpcResult(id: any, result: any): Response {
  return Response.json({ jsonrpc: "2.0", id: id ?? null, result });
}

function rpcError(id: any, code: number, message: string): Response {
  return Response.json({ jsonrpc: "2.0", id: id ?? null, error: { code, message } });
}

async function handleRpc(
  body: JsonRpcRequest,
  env: Env,
  ctx: ExecutionContext
): Promise<Response> {
  // Notifications (no id) → 202 Accepted, no body.
  if (body.id === undefined && body.method?.startsWith("notifications/")) {
    return new Response(null, { status: 202 });
  }

  switch (body.method) {
    case "initialize":
      return rpcResult(body.id, {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: { tools: {} },
        serverInfo: {
          name: "mcprated",
          version: env.SERVER_VERSION ?? "0.1.0",
        },
      });

    case "tools/list":
      return rpcResult(body.id, { tools: TOOLS });

    case "tools/call": {
      const name = body.params?.name;
      const args = body.params?.arguments;
      if (!name) return rpcError(body.id, -32602, "missing tool name");
      try {
        const result = await callTool(env, ctx, name, args);
        return rpcResult(body.id, result);
      } catch (e: any) {
        return rpcError(body.id, -32603, e?.message ?? "tool error");
      }
    }

    case "ping":
      return rpcResult(body.id, {});

    default:
      return rpcError(body.id, -32601, `method not found: ${body.method}`);
  }
}

// ---------------------------------------------------------------------------
// Worker entry
// ---------------------------------------------------------------------------

export default {
  async fetch(
    request: Request,
    env: Env,
    ctx: ExecutionContext
  ): Promise<Response> {
    const url = new URL(request.url);

    // Friendly index for GET (browser visit, health check, debugging)
    if (request.method === "GET") {
      return new Response(
        [
          "MCPRated MCP server",
          "",
          "POST JSON-RPC 2.0 to this endpoint to call MCP tools.",
          "",
          "Methods: initialize, tools/list, tools/call",
          "Tools:   " + TOOLS.map((t) => t.name).join(", "),
          "",
          "Catalog: " + env.CATALOG_BASE,
          "Manifest: " + env.CATALOG_BASE + "/api/v1/manifest.json",
          "Repo:    https://github.com/mcprated/mcprated",
        ].join("\n"),
        {
          status: 200,
          headers: { "content-type": "text/plain; charset=utf-8" },
        }
      );
    }

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, GET, OPTIONS",
          "access-control-allow-headers": "content-type, mcp-session-id",
        },
      });
    }

    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405 });
    }

    let body: JsonRpcRequest;
    try {
      body = (await request.json()) as JsonRpcRequest;
    } catch {
      return rpcError(null, -32700, "parse error");
    }

    if (body.jsonrpc !== "2.0") {
      return rpcError(body.id ?? null, -32600, "invalid jsonrpc version");
    }

    const response = await handleRpc(body, env, ctx);

    // CORS for browser-based MCP clients (Inspector, web playgrounds).
    response.headers.set("access-control-allow-origin", "*");
    return response;
  },
};
