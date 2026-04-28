/**
 * Bug #6 fix: free-text 'search' tool for when find_server's enum doesn't fit.
 * Verifies relevance × quality ranking and graceful empty-result handling.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { fetchMock, callTool, mockUpstream, mockUpstream404 } from "./helpers";

function unwrap(body: any) {
  return JSON.parse(body.result.content[0].text);
}

describe("Bug #6: search tool", () => {
  beforeEach(() => {
    fetchMock.activate();
    fetchMock.disableNetConnect();
  });

  it("requires a query of length >= 2", async () => {
    const { body } = await callTool("search", { query: "" });
    expect((body as any).error?.code).toBe(-32602);
  });

  it("matches by description token", async () => {
    mockUpstream("/index.json", {
      servers: [
        { repo: "x/postgres-mcp", slug: "x__postgres-mcp", composite: 90,
          description: "MCP for Postgres databases", capabilities: ["database"], kind: "server" },
        { repo: "y/browser-mcp", slug: "y__browser-mcp", composite: 80,
          description: "Browser automation", capabilities: ["web"], kind: "server" },
      ],
    });
    const { body } = await callTool("search", { query: "postgres", limit: 5 });
    const payload = unwrap(body);
    expect(payload.query).toBe("postgres");
    expect(payload.servers).toHaveLength(1);
    expect(payload.servers[0].slug).toBe("x__postgres-mcp");
  });

  it("ranks higher-quality matches first", async () => {
    mockUpstream("/index.json", {
      servers: [
        { repo: "junk/postgres", slug: "junk__postgres", composite: 30,
          description: "postgres tool", capabilities: ["database"], kind: "server" },
        { repo: "good/postgres", slug: "good__postgres", composite: 95,
          description: "postgres server", capabilities: ["database"], kind: "server" },
      ],
    });
    const { body } = await callTool("search", { query: "postgres" });
    const payload = unwrap(body);
    // Both hit the same number of tokens, but quality breaks ties.
    expect(payload.servers[0].slug).toBe("good__postgres");
  });

  it("filters out non-server kinds", async () => {
    mockUpstream("/index.json", {
      servers: [
        { repo: "a/postgres-mcp", slug: "a__postgres-mcp", composite: 80,
          description: "postgres", capabilities: ["database"], kind: "server" },
        { repo: "b/postgres-client", slug: "b__postgres-client", composite: 80,
          description: "postgres", capabilities: ["database"], kind: "client" },
      ],
    });
    const { body } = await callTool("search", { query: "postgres" });
    const payload = unwrap(body);
    expect(payload.servers).toHaveLength(1);
    expect(payload.servers[0].slug).toBe("a__postgres-mcp");
  });

  it("returns zero results for unrecognized term", async () => {
    mockUpstream("/index.json", {
      servers: [
        { repo: "x/foo", slug: "x__foo", composite: 90,
          description: "An MCP", capabilities: ["devtools"], kind: "server" },
      ],
    });
    const { body } = await callTool("search", { query: "quantumcryptopickle" });
    const payload = unwrap(body);
    expect(payload.total_matches).toBe(0);
    expect(payload.servers).toHaveLength(0);
  });

  it("respects limit", async () => {
    mockUpstream("/index.json", {
      servers: Array.from({ length: 20 }, (_, i) => ({
        repo: `x/postgres-${i}`, slug: `x__postgres-${i}`, composite: 50,
        description: "postgres", capabilities: ["database"], kind: "server",
      })),
    });
    const { body } = await callTool("search", { query: "postgres", limit: 3 });
    const payload = unwrap(body);
    expect(payload.servers).toHaveLength(3);
    expect(payload.total_matches).toBe(20);
  });

  // ---------------------------------------------------------------------------
  // Local-test feedback (cold-agent run on localhost:8788) flagged search
  // recall: `query="browser"` returned only `executeautomation/mcp-playwright`,
  // missing `microsoft/playwright-mcp` because its description doesn't
  // contain the literal word "browser" — only "Playwright". Same for
  // `query="postgres"` returning a single hit when supabase + multiple
  // database servers should be relevant.
  //
  // Fix: expand the query against the capability taxonomy. If a query token
  // is itself a capability keyword (browser → web, postgres → database),
  // also include servers tagged with that capability in the candidate set.
  // ---------------------------------------------------------------------------
  describe("synonym expansion via taxonomy (cold-agent recall fix)", () => {
    it("'browser' matches servers tagged 'web' even without literal token in desc", async () => {
      mockUpstream("/index.json", {
        servers: [
          {
            repo: "microsoft/playwright-mcp",
            slug: "microsoft__playwright-mcp",
            composite: 100,
            description: "Playwright Model Context Protocol Server",
            capabilities: ["web", "ai"],
            kind: "server",
          },
          {
            repo: "x/notes",
            slug: "x__notes",
            composite: 70,
            description: "Sticky notes server",
            capabilities: ["memory"],
            kind: "server",
          },
        ],
      });
      const { body } = await callTool("search", { query: "browser" });
      const payload = unwrap(body);
      const slugs = payload.servers.map((s: any) => s.slug);
      expect(slugs).toContain("microsoft__playwright-mcp");
    });

    it("'postgres' matches servers tagged 'database' (taxonomy expansion)", async () => {
      mockUpstream("/index.json", {
        servers: [
          { repo: "x/supabase-mcp", slug: "x__supabase-mcp", composite: 92,
            description: "Connect Supabase to your AI assistants",
            capabilities: ["database", "ai"], kind: "server" },
          { repo: "x/qdrant-mcp", slug: "x__qdrant-mcp", composite: 82,
            description: "Vector search for Qdrant",
            capabilities: ["database", "search"], kind: "server" },
          { repo: "x/sticky-notes", slug: "x__notes", composite: 50,
            description: "Notes", capabilities: ["memory"], kind: "server" },
        ],
      });
      const { body } = await callTool("search", { query: "postgres" });
      const payload = unwrap(body);
      const slugs = payload.servers.map((s: any) => s.slug);
      expect(slugs).toContain("x__supabase-mcp");
      expect(slugs).toContain("x__qdrant-mcp");
      expect(slugs).not.toContain("x__notes");
    });

    it("direct token match still wins over taxonomy expansion", async () => {
      mockUpstream("/index.json", {
        servers: [
          { repo: "x/db-direct", slug: "x__db-direct", composite: 70,
            description: "MCP for postgres tables",  // literal hit
            capabilities: ["database"], kind: "server" },
          { repo: "x/db-tag", slug: "x__db-tag", composite: 95,
            description: "MCP for SQL access",  // no literal "postgres"
            capabilities: ["database"], kind: "server" },
        ],
      });
      const { body } = await callTool("search", { query: "postgres" });
      const payload = unwrap(body);
      // Direct hit gets relevance=1.0 vs expansion=0.5; despite lower
      // composite the literal-match server should rank first.
      expect(payload.servers[0].slug).toBe("x__db-direct");
    });
  });

  // Schema declares minLength: 2 for query — server must enforce.
  describe("minLength enforcement on query", () => {
    it("query of length 1 → -32602 with minLength message", async () => {
      const { body } = await callTool("search", { query: "x" });
      expect((body as any).error?.code).toBe(-32602);
      const msg = ((body as any).error?.message ?? "").toLowerCase();
      expect(msg).toMatch(/length|character|too short|min/);
    });
  });
});

// Long-input truncation: vet/server_detail/alternatives error messages
// shouldn't echo a multi-hundred-character malformed slug verbatim.
describe("error message truncation for runaway inputs", () => {
  beforeEach(() => {
    fetchMock.activate();
    fetchMock.disableNetConnect();
  });

  it("vet with 300-char slug → error message <= 200 chars", async () => {
    const longSlug = "a".repeat(300);
    mockUpstream404(`/api/v1/vet/${longSlug}.json`);
    const { body } = await callTool("vet", { slug: longSlug });
    const msg = (body as any).error?.message ?? "";
    expect(msg.length).toBeLessThanOrEqual(200);
  });
});
