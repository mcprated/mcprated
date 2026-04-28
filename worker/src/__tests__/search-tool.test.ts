/**
 * Bug #6 fix: free-text 'search' tool for when find_server's enum doesn't fit.
 * Verifies relevance × quality ranking and graceful empty-result handling.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { fetchMock, callTool, mockUpstream } from "./helpers";

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
});
