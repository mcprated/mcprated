/**
 * Tool dispatch: each of the 6 tools, with mocked upstream catalog.
 * Verifies the proxy + content envelope path end-to-end.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { fetchMock, callTool, mockUpstream } from "./helpers";

const SAMPLE_SERVER = {
  repo: "acme/foo",
  slug: "acme__foo",
  composite: 90,
  axes: { reliability: 90, documentation: 90, trust: 90, community: 90 },
  kind: "server",
  subkind: "integration",
  capabilities: ["database"],
  stars: 100,
};

function unwrap(body: any) {
  return JSON.parse(body.result.content[0].text);
}

describe("tool dispatch (with mocked upstream)", () => {
  beforeEach(() => {
    fetchMock.activate();
    fetchMock.disableNetConnect();
  });

  it("find_server returns servers from by-capability shard", async () => {
    mockUpstream("/mcprated/api/v1/by-capability/database.json", {
      capability: "database",
      count: 1,
      servers: [SAMPLE_SERVER],
    });
    const { body } = await callTool("find_server", { capability: "database", limit: 5 });
    expect((body as any).error).toBeUndefined();
    const payload = unwrap(body);
    expect(payload.capability).toBe("database");
    expect(payload.servers).toHaveLength(1);
    expect(payload.servers[0].repo).toBe("acme/foo");
  });

  it("find_server respects limit", async () => {
    mockUpstream("/mcprated/api/v1/by-capability/web.json", {
      capability: "web",
      count: 5,
      servers: Array(5).fill(SAMPLE_SERVER),
    });
    const { body } = await callTool("find_server", { capability: "web", limit: 2 });
    const payload = unwrap(body);
    expect(payload.servers).toHaveLength(2);
  });

  it("vet returns trust subset", async () => {
    mockUpstream("/mcprated/api/v1/vet/acme__foo.json", {
      repo: "acme/foo", verdict: "verified", composite: 90,
    });
    const { body } = await callTool("vet", { slug: "acme__foo" });
    const payload = unwrap(body);
    expect(payload.verdict).toBe("verified");
  });

  it("alternatives returns capability-similar servers", async () => {
    mockUpstream("/mcprated/api/v1/alternatives/acme__foo.json", {
      for: "acme/foo",
      alternatives: [{ ...SAMPLE_SERVER, similarity: 0.67 }],
    });
    const { body } = await callTool("alternatives", { slug: "acme__foo" });
    const payload = unwrap(body);
    expect(payload.alternatives[0].similarity).toBe(0.67);
  });

  it("by_kind returns kind-filtered servers", async () => {
    mockUpstream("/mcprated/api/v1/by-kind/server.json", {
      kind: "server",
      count: 1,
      servers: [SAMPLE_SERVER],
    });
    const { body } = await callTool("by_kind", { kind: "server" });
    const payload = unwrap(body);
    expect(payload.kind).toBe("server");
  });

  it("top picks the requested ranking", async () => {
    mockUpstream("/mcprated/api/v1/top.json", {
      by_composite: [SAMPLE_SERVER],
      by_stars: [{ ...SAMPLE_SERVER, slug: "different" }],
      by_recency: [],
    });
    const { body } = await callTool("top", { ranking: "stars", limit: 5 });
    const payload = unwrap(body);
    expect(payload.ranking).toBe("stars");
    expect(payload.servers[0].slug).toBe("different");
  });

  it("server_detail returns full per-server JSON", async () => {
    mockUpstream("/mcprated/servers/acme__foo.json", {
      repo: "acme/foo",
      composite: 90,
      axes: { reliability: { score: 90 } },
      hard_flags: [],
    });
    const { body } = await callTool("server_detail", { slug: "acme__foo" });
    const payload = unwrap(body);
    expect(payload.repo).toBe("acme/foo");
    expect(payload.composite).toBe(90);
  });
});
