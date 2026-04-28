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
      "Find MCP servers tagged with a controlled capability category. Use when you can map your need to one of the 12 categories below; if you can't, use 'search' instead.\n\n" +
      "Mapping examples:\n" +
      "  Postgres / MySQL / SQLite / any SQL or NoSQL DB → 'database'\n" +
      "  Local files, read/write filesystem → 'filesystem'\n" +
      "  Browser automation, scraping, HTTP fetch → 'web'\n" +
      "  Vector search, RAG, retrieval, search engines → 'search'\n" +
      "  Notion, Jira, Linear, calendar, docs → 'productivity'\n" +
      "  Slack, Discord, SMTP, Twilio → 'comms'\n" +
      "  GitHub, GitLab, Docker, Kubernetes, CI → 'devtools'\n" +
      "  AWS, GCP, Azure, Cloudflare, Vercel → 'cloud'\n" +
      "  OpenAI, Anthropic, image-gen, transcription → 'ai'\n" +
      "  Knowledge graph, notes, Obsidian → 'memory'\n" +
      "  Stripe, payments, blockchain → 'finance'\n" +
      "  FFmpeg, OCR, image/video processing → 'media'\n\n" +
      "Returns up to 'limit' servers ranked by composite quality score.",
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
          description:
            "Controlled vocabulary tag from taxonomy v1.0. " +
            "If your need doesn't fit (e.g. 'crypto trading bot'), use 'search' tool with free text.",
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
    name: "search",
    description:
      "Free-text search across the catalog when 'find_server' enum doesn't fit. Matches against repo name, description, and capability tags. Returns up to 'limit' servers, ranked by relevance and quality. Use this for natural-language needs like 'postgres mcp', 'browser automation', 'github operations' — the matcher will translate.",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          minLength: 2,
          description: "Free-text search term (e.g. 'postgres', 'browser automation').",
        },
        limit: {
          type: "integer",
          default: 10,
          minimum: 1,
          maximum: 25,
        },
      },
      required: ["query"],
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
// Typed errors — every error path through this Worker raises one of these.
// rpcError() in handleRpc() converts them to JSON-RPC envelopes.
//
// Bug #1 fix: messages are agent-facing only. They MUST NOT contain the
// upstream URL, internal paths, query strings, or anything that leaks how
// the catalog is hosted.
// ---------------------------------------------------------------------------

class JsonRpcError extends Error {
  constructor(public code: number, message: string) {
    super(message);
    this.name = "JsonRpcError";
  }
}

function invalidParams(msg: string): never {
  throw new JsonRpcError(-32602, msg);
}

function notFound(msg: string): never {
  // We use -32602 for "not found" rather than a custom server-error code:
  // from the agent's POV, asking for a non-existent slug IS bad input.
  // The agent should retry with a valid slug, not back off thinking the
  // server is broken (which -32603 implies).
  throw new JsonRpcError(-32602, msg);
}

function internal(msg: string): never {
  throw new JsonRpcError(-32603, msg);
}

class CatalogNotFound extends Error {}
class CatalogUnavailable extends Error {}

// ---------------------------------------------------------------------------
// HTTP / cache helpers
// ---------------------------------------------------------------------------

// Bumped per-deploy to bust any stale CF colo cache entries.
const CATALOG_CACHE_VERSION = "5";

// ---------------------------------------------------------------------------
// Search synonym expansion — local-test feedback: query="browser" missed
// microsoft/playwright-mcp because its description doesn't contain "browser",
// only "Playwright". Map common natural-language tokens to capability tags;
// servers tagged with the matched capability join the candidate set with
// 0.5 weight (literal hits still dominate at 1.0).
//
// Sourced from linter/taxonomy/v1.yaml — keep in sync. We deliberately don't
// fetch the taxonomy at runtime: the mapping is small (one-token → capability)
// and bundling it makes search work even if the catalog index is partially
// stale.
// ---------------------------------------------------------------------------
const TAXONOMY_TOKEN_TO_CAPABILITY: Record<string, string> = {
  // database
  postgres: "database", postgresql: "database", mysql: "database",
  sqlite: "database", mongo: "database", mongodb: "database", redis: "database",
  neo4j: "database", sql: "database", duckdb: "database", supabase: "database",
  firestore: "database", dynamodb: "database", clickhouse: "database",
  bigquery: "database", snowflake: "database", database: "database", rdbms: "database",
  // web
  browser: "web", playwright: "web", puppeteer: "web", chromium: "web",
  scraping: "web", "web-scraping": "web",
  // search
  retrieval: "search", elasticsearch: "search", rag: "search", embeddings: "search",
  // productivity
  notion: "productivity", todoist: "productivity", asana: "productivity",
  jira: "productivity", gmail: "productivity", outlook: "productivity",
  confluence: "productivity", airtable: "productivity",
  // comms
  slack: "comms", discord: "comms", telegram: "comms", whatsapp: "comms",
  twilio: "comms", smtp: "comms", imap: "comms", mattermost: "comms",
  // devtools
  github: "devtools", gitlab: "devtools", bitbucket: "devtools",
  sentry: "devtools", datadog: "devtools", docker: "devtools",
  kubernetes: "devtools", terraform: "devtools", ansible: "devtools",
  // cloud
  aws: "cloud", gcp: "cloud", azure: "cloud", cloudflare: "cloud",
  vercel: "cloud", netlify: "cloud", heroku: "cloud", lambda: "cloud", s3: "cloud",
  // ai
  openai: "ai", anthropic: "ai", llm: "ai", whisper: "ai",
  replicate: "ai", huggingface: "ai", gemini: "ai",
  // memory
  obsidian: "memory", anki: "memory",
  // finance
  stripe: "finance", plaid: "finance", payments: "finance", blockchain: "finance",
  ethereum: "finance", bitcoin: "finance", coinbase: "finance",
  // media
  ffmpeg: "media", ocr: "media",
};

// Cap on how much of the offending input we echo back in error messages.
// 80 chars is enough to tell the agent which slug it tried; longer is noise
// and risks log/UI bloat if the input is malicious or runaway-generated.
const ERROR_INPUT_ECHO_MAX = 80;

function safeQuote(value: unknown): string {
  const s = String(value);
  if (s.length <= ERROR_INPUT_ECHO_MAX) return JSON.stringify(s);
  return JSON.stringify(s.slice(0, ERROR_INPUT_ECHO_MAX) + "…");
}

async function fetchCatalog(
  env: Env,
  ctx: ExecutionContext,
  path: string
): Promise<any> {
  const url = `${env.CATALOG_BASE}${path}?_v=${CATALOG_CACHE_VERSION}`;
  const cache = caches.default;
  const cacheKey = new Request(url, { method: "GET" });

  let cached = await cache.match(cacheKey);
  if (cached) {
    return cached.json();
  }

  const upstream = await fetch(url);
  if (upstream.status === 404) {
    // Throw a typed error; tools attach their own context (slug, capability)
    // before re-raising as JsonRpcError. The URL never reaches the agent.
    throw new CatalogNotFound();
  }
  if (!upstream.ok) {
    throw new CatalogUnavailable();
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
// Schema-driven argument validation (Bug #2 fix)
//
// MCP clients are expected to validate args against the inputSchema we declare
// in tools/list, but we never trust the client. Every enum and required field
// is enforced server-side here, with helpful error messages that tell the
// agent what went wrong AND what it could try next.
// ---------------------------------------------------------------------------

function validateArgs(toolName: string, rawArgs: unknown): Record<string, unknown> {
  const tool = TOOLS.find((t) => t.name === toolName);
  if (!tool) {
    invalidParams(
      `unknown tool '${toolName}'. Valid tools: ${TOOLS.map((t) => t.name).join(", ")}`
    );
  }
  const args: Record<string, unknown> =
    rawArgs && typeof rawArgs === "object" ? { ...(rawArgs as object) } : {};
  const schema = tool.inputSchema as unknown as {
    properties?: Record<string, { type?: string; enum?: unknown[]; minLength?: number }>;
    required?: string[];
  };

  for (const req of schema.required ?? []) {
    if (args[req] === undefined || args[req] === null || args[req] === "") {
      invalidParams(`missing required field '${req}' for tool '${toolName}'`);
    }
  }

  for (const [key, propSchema] of Object.entries(schema.properties ?? {})) {
    if (args[key] === undefined) continue;
    if (propSchema.enum && !propSchema.enum.includes(args[key])) {
      invalidParams(
        `invalid '${key}': ${safeQuote(args[key])}. Valid values: ${propSchema.enum
          .map((v) => JSON.stringify(v))
          .join(", ")}`
      );
    }
    if (
      propSchema.minLength !== undefined &&
      typeof args[key] === "string" &&
      (args[key] as string).length < propSchema.minLength
    ) {
      invalidParams(
        `'${key}' must be at least ${propSchema.minLength} characters; got ${(args[key] as string).length}`
      );
    }
  }

  return args;
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
  rawArgs: any
): Promise<any> {
  // Validate first — never fetch with bad input. validateArgs throws -32602
  // before we'd hit upstream and 404 (which would leak via Bug #1).
  const a = validateArgs(name, rawArgs);

  switch (name) {
    case "find_server": {
      const cap = String(a.capability).trim();
      const limit = Math.max(1, Math.min(50, Number(a.limit ?? 10)));
      try {
        const data = await fetchCatalog(env, ctx, `/api/v1/by-capability/${cap}.json`);
        const servers = (data.servers ?? []).slice(0, limit);
        return contentEnvelope({
          capability: cap,
          total_matches: data.count,
          returned: servers.length,
          servers,
        });
      } catch (e) {
        if (e instanceof CatalogNotFound) {
          // Capability passed enum validation, so this means catalog hasn't
          // been published yet (or capability shard is missing).
          notFound(`no servers indexed for capability '${cap}' yet. Try 'top' or another capability.`);
        }
        if (e instanceof CatalogUnavailable) internal("catalog upstream unavailable");
        throw e;
      }
    }

    case "search": {
      const query = String(a.query).trim().toLowerCase();
      const limit = Math.max(1, Math.min(25, Number(a.limit ?? 10)));
      try {
        const data = await fetchCatalog(env, ctx, `/index.json`);
        const tokens = query.split(/\s+/).filter((t) => t.length >= 2);

        // Synonym expansion: any token that matches a known taxonomy keyword
        // (postgres, browser, slack, ...) maps to its capability tag (database,
        // web, comms, ...). Servers tagged with that capability join the
        // candidate set with reduced weight. Local-test feedback flagged the
        // miss: query="browser" missed microsoft/playwright-mcp because its
        // description was "Playwright Model Context Protocol Server" — no
        // literal "browser". With expansion, web-tagged servers are surfaced.
        const expandedCapabilities = new Set<string>();
        for (const t of tokens) {
          const cap = TAXONOMY_TOKEN_TO_CAPABILITY[t];
          if (cap) expandedCapabilities.add(cap);
        }

        const scored = (data.servers ?? [])
          .filter((s: any) => s.kind === "server")
          .map((s: any) => {
            const hay = [
              s.repo, s.description, ...(s.capabilities ?? []), s.language,
            ].filter(Boolean).join(" ").toLowerCase();
            // Direct hits: literal substring match against the haystack.
            const directHits = tokens.reduce(
              (n, t) => n + (hay.includes(t) ? 1 : 0), 0
            );
            // Expansion match: server tagged with one of the capabilities
            // implied by the query. Half-weight so direct hits still win.
            const caps = new Set<string>(s.capabilities ?? []);
            const expansionHit = [...expandedCapabilities].some((c) => caps.has(c));
            const directRelevance = tokens.length ? directHits / tokens.length : 0;
            const expansionRelevance = expansionHit ? 0.5 : 0;
            const relevance = Math.max(directRelevance, expansionRelevance);
            const quality = Math.sqrt((s.composite ?? 0) / 100);
            return {
              s, score: relevance * quality,
              direct_hits: directHits, relevance,
              matched_via_expansion: expansionHit && directRelevance === 0,
            };
          })
          .filter((x: any) => x.relevance > 0)
          .sort((a: any, b: any) => b.score - a.score || b.s.composite - a.s.composite);
        const top = scored.slice(0, limit).map((x: any) => ({
          ...x.s,
          search_score: Number(x.score.toFixed(3)),
          token_hits: x.direct_hits,
          matched_via: x.matched_via_expansion ? "capability_expansion" : "direct",
        }));
        return contentEnvelope({
          query,
          tokens,
          expanded_capabilities: [...expandedCapabilities],
          total_matches: scored.length,
          returned: top.length,
          servers: top,
        });
      } catch (e) {
        if (e instanceof CatalogNotFound) internal("catalog index missing");
        if (e instanceof CatalogUnavailable) internal("catalog upstream unavailable");
        throw e;
      }
    }

    case "vet": {
      const slug = String(a.slug).trim();
      try {
        const data = await fetchCatalog(env, ctx, `/api/v1/vet/${slug}.json`);
        return contentEnvelope(data);
      } catch (e) {
        if (e instanceof CatalogNotFound) {
          notFound(
            `no server with slug ${safeQuote(slug)}. Use 'top' or 'find_server' to discover valid slugs (format: <owner>__<repo>).`
          );
        }
        if (e instanceof CatalogUnavailable) internal("catalog upstream unavailable");
        throw e;
      }
    }

    case "alternatives": {
      const slug = String(a.slug).trim();
      try {
        const data = await fetchCatalog(env, ctx, `/api/v1/alternatives/${slug}.json`);
        return contentEnvelope(data);
      } catch (e) {
        if (e instanceof CatalogNotFound) {
          notFound(
            `no server with slug ${safeQuote(slug)}. Use 'top' or 'find_server' to discover valid slugs.`
          );
        }
        if (e instanceof CatalogUnavailable) internal("catalog upstream unavailable");
        throw e;
      }
    }

    case "by_kind": {
      const kind = String(a.kind).trim();
      try {
        const data = await fetchCatalog(env, ctx, `/api/v1/by-kind/${kind}.json`);
        return contentEnvelope(data);
      } catch (e) {
        if (e instanceof CatalogNotFound) {
          notFound(`no entries indexed for kind '${kind}' yet.`);
        }
        if (e instanceof CatalogUnavailable) internal("catalog upstream unavailable");
        throw e;
      }
    }

    case "top": {
      const ranking = String(a.ranking ?? "composite");
      const limit = Math.max(1, Math.min(25, Number(a.limit ?? 10)));
      try {
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
      } catch (e) {
        if (e instanceof CatalogNotFound) internal("catalog top.json missing");
        if (e instanceof CatalogUnavailable) internal("catalog upstream unavailable");
        throw e;
      }
    }

    case "server_detail": {
      const slug = String(a.slug).trim();
      try {
        const data = await fetchCatalog(env, ctx, `/servers/${slug}.json`);
        return contentEnvelope(data);
      } catch (e) {
        if (e instanceof CatalogNotFound) {
          notFound(
            `no server with slug ${safeQuote(slug)}. Use 'top' or 'find_server' to discover valid slugs.`
          );
        }
        if (e instanceof CatalogUnavailable) internal("catalog upstream unavailable");
        throw e;
      }
    }

    default:
      // validateArgs already rejects unknown tools, so this is unreachable —
      // keep it for type narrowing and as a defense-in-depth fallback.
      invalidParams(`unknown tool '${name}'`);
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
        if (e instanceof JsonRpcError) {
          return rpcError(body.id, e.code, e.message);
        }
        // Last-resort: unexpected runtime error. Don't leak `e.message` —
        // it might contain stack-trace fragments or upstream URLs.
        return rpcError(body.id, -32603, "internal error");
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
