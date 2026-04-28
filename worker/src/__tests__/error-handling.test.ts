/**
 * Bug #1 fix: error responses must NEVER leak the upstream URL or internal
 * paths. They must use the correct JSON-RPC error code:
 *   -32602 Invalid Params      — bad input, unknown enum, missing field, not-found
 *   -32603 Internal Error      — actual server failure (upstream 5xx, parse fail)
 *   -32601 Method Not Found    — already handled
 *
 * These tests are written BEFORE the fix and pin the desired contract.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { fetchMock, callTool, mockUpstream404 } from "./helpers";

describe("Bug #1: error responses are sanitized + use correct codes", () => {
  beforeEach(() => {
    fetchMock.activate();
    fetchMock.disableNetConnect();
  });

  it("404 from upstream → -32602 (not -32603)", async () => {
    mockUpstream404("/api/v1/vet/doesnt__exist.json");
    const { body } = await callTool("vet", { slug: "doesnt__exist" });
    expect((body as any).error?.code).toBe(-32602);
  });

  it("error message does NOT leak the upstream URL", async () => {
    mockUpstream404("/api/v1/vet/something.json");
    const { body } = await callTool("vet", { slug: "something" });
    const msg = (body as any).error?.message ?? "";
    expect(msg).not.toContain("github.io");
    expect(msg).not.toContain("mcprated.github.io");
    expect(msg).not.toContain("/api/v1/");
    expect(msg).not.toContain("?_v=");
  });

  it("error message tells the agent what went wrong (not just 'upstream 404')", async () => {
    mockUpstream404("/api/v1/vet/no-such-slug.json");
    const { body } = await callTool("vet", { slug: "no-such-slug" });
    const msg = ((body as any).error?.message ?? "").toLowerCase();
    // Should mention the bad slug + what the agent could do next.
    expect(msg).toContain("no-such-slug");
  });

  it("upstream 5xx → -32603 with sanitized message", async () => {
    fetchMock
      .get("https://mcprated.github.io")
      .intercept({ path: /^\/mcprated\/api\/v1\/by-capability\/database\.json\?/ })
      .reply(503, "service unavailable", { headers: { "content-type": "text/plain" } });
    const { body } = await callTool("find_server", { capability: "database" });
    const code = (body as any).error?.code;
    expect(code).toBe(-32603);
    const msg = (body as any).error?.message ?? "";
    expect(msg).not.toContain("github.io");
    expect(msg).not.toContain("/api/v1/");
  });
});
