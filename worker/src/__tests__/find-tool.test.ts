/**
 * find_tool: agent has a specific tool need (a name like 'browser_navigate'
 * or natural-language intent like 'send slack message') and wants the tool
 * surfaced regardless of which server hosts it.
 *
 * Backed by /api/v1/tools-index.json — flat list of every extracted tool
 * across every server.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { fetchMock, callTool, mockUpstream } from "./helpers";

function unwrap(body: any) {
  return JSON.parse(body.result.content[0].text);
}

describe("find_tool — agent searches at the tool level", () => {
  beforeEach(() => {
    fetchMock.activate();
    fetchMock.disableNetConnect();
  });

  it("is registered in tools/list", async () => {
    const res = await callTool("find_tool", { intent: "" });
    // we expect schema validation to fire on minLength, not 'unknown tool'
    expect((res.body as any).error?.code).toBe(-32602);
  });

  it("matches by exact tool name", async () => {
    mockUpstream("/api/v1/tools-index.json", {
      total_tools: 3,
      tools: [
        { name: "browser_navigate", repo: "microsoft/playwright-mcp", slug: "microsoft__playwright-mcp", composite: 100, capabilities: ["web"] },
        { name: "browser_click",    repo: "microsoft/playwright-mcp", slug: "microsoft__playwright-mcp", composite: 100, capabilities: ["web"] },
        { name: "read_file",        repo: "ref/filesystem-mcp",      slug: "ref__filesystem-mcp",      composite: 90,  capabilities: ["filesystem"] },
      ],
    });
    const { body } = await callTool("find_tool", { intent: "browser_navigate" });
    const payload = unwrap(body);
    // Tokens "browser" + "navigate" → browser_navigate hits both; browser_click
    // hits one. Both surface but the exact match must rank first.
    expect(payload.matches[0].name).toBe("browser_navigate");
    expect(payload.matches[0].repo).toBe("microsoft/playwright-mcp");
  });

  it("matches by natural-language intent (token overlap)", async () => {
    mockUpstream("/api/v1/tools-index.json", {
      total_tools: 3,
      tools: [
        { name: "browser_navigate", repo: "x/playwright", slug: "x__playwright", composite: 100, capabilities: ["web"] },
        { name: "click_element",    repo: "x/playwright", slug: "x__playwright", composite: 100, capabilities: ["web"] },
        { name: "read_file",        repo: "x/files",      slug: "x__files",      composite: 80,  capabilities: ["filesystem"] },
      ],
    });
    const { body } = await callTool("find_tool", { intent: "navigate browser" });
    const payload = unwrap(body);
    // browser_navigate should match — both tokens hit
    expect(payload.matches[0].name).toBe("browser_navigate");
  });

  it("ranks by quality when multiple servers expose the same tool name", async () => {
    mockUpstream("/api/v1/tools-index.json", {
      total_tools: 2,
      tools: [
        { name: "read_file", repo: "junk/clone",          slug: "junk__clone",          composite: 30, capabilities: ["filesystem"] },
        { name: "read_file", repo: "ref/filesystem-mcp",  slug: "ref__filesystem-mcp",  composite: 95, capabilities: ["filesystem"] },
      ],
    });
    const { body } = await callTool("find_tool", { intent: "read_file" });
    const payload = unwrap(body);
    expect(payload.matches[0].slug).toBe("ref__filesystem-mcp");
  });

  it("respects limit", async () => {
    mockUpstream("/api/v1/tools-index.json", {
      total_tools: 50,
      tools: Array.from({ length: 50 }, (_, i) => ({
        name: `tool_${i}`, repo: `x/r${i}`, slug: `x__r${i}`, composite: 50,
        capabilities: ["devtools"],
      })),
    });
    const { body } = await callTool("find_tool", { intent: "tool", limit: 5 });
    const payload = unwrap(body);
    expect(payload.matches).toHaveLength(5);
  });

  it("returns empty matches with helpful payload when nothing matches", async () => {
    mockUpstream("/api/v1/tools-index.json", {
      total_tools: 1,
      tools: [{ name: "foo", repo: "x/y", slug: "x__y", composite: 50, capabilities: [] }],
    });
    const { body } = await callTool("find_tool", { intent: "quantum-cryptography" });
    const payload = unwrap(body);
    expect(payload.matches).toEqual([]);
    expect(payload.total_indexed).toBe(1);
  });

  // G4: tools-index now carries description + input_keys. find_tool must
  // search those too — that's the whole point of "intent-based" lookup.
  describe("intent matching against descriptions (G4)", () => {
    it("matches tool whose description contains query but name does not", async () => {
      mockUpstream("/api/v1/tools-index.json", {
        total_tools: 2,
        tools: [
          {
            name: "query",
            description: "List all rows in a Postgres table",
            input_keys: ["table_name"],
            repo: "x/db", slug: "x__db", composite: 80, capabilities: ["database"],
          },
          {
            name: "ping",
            description: "Health check",
            input_keys: [],
            repo: "y/util", slug: "y__util", composite: 70, capabilities: [],
          },
        ],
      });
      const { body } = await callTool("find_tool", { intent: "postgres" });
      const payload = unwrap(body);
      expect(payload.matches[0].name).toBe("query");
    });

    it("name match outranks description match for same query", async () => {
      mockUpstream("/api/v1/tools-index.json", {
        total_tools: 2,
        tools: [
          {
            name: "browser_click",
            description: "Click an element",
            input_keys: ["selector"],
            repo: "x/play", slug: "x__play", composite: 100, capabilities: ["web"],
          },
          {
            name: "scrape",
            description: "Fetch a page in a headless browser",
            input_keys: ["url"],
            repo: "y/scraper", slug: "y__scraper", composite: 100, capabilities: ["web"],
          },
        ],
      });
      const { body } = await callTool("find_tool", { intent: "browser" });
      const payload = unwrap(body);
      // Both match (name vs description). Name match should rank higher
      // because of the 0.3 nameHits bonus on top of 0.7 directHits.
      expect(payload.matches[0].name).toBe("browser_click");
    });

    it("input_keys are searchable too", async () => {
      mockUpstream("/api/v1/tools-index.json", {
        total_tools: 1,
        tools: [
          {
            name: "execute",
            description: "Run code",
            input_keys: ["sql_query", "limit"],
            repo: "x/db", slug: "x__db", composite: 80, capabilities: ["database"],
          },
        ],
      });
      const { body } = await callTool("find_tool", { intent: "sql_query" });
      const payload = unwrap(body);
      expect(payload.matches).toHaveLength(1);
    });
  });
});
