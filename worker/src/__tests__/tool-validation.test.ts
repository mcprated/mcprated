/**
 * Bug #2 fix: server-side enum + required-field enforcement.
 *
 * Schema declares enums; the implementation must reject invalid values
 * with -32602 BEFORE attempting an upstream fetch (which would 404 and
 * leak the URL via Bug #1).
 *
 * These tests are written BEFORE the fix.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { fetchMock, callTool } from "./helpers";

describe("Bug #2: server enforces its declared inputSchema", () => {
  beforeEach(() => {
    fetchMock.activate();
    fetchMock.disableNetConnect();
  });

  describe("find_server.capability enum", () => {
    it("rejects capability not in enum", async () => {
      const { body } = await callTool("find_server", { capability: "blockchain" });
      expect((body as any).error?.code).toBe(-32602);
    });

    it("error message lists valid capability values", async () => {
      const { body } = await callTool("find_server", { capability: "blockchain" });
      const msg = ((body as any).error?.message ?? "").toLowerCase();
      // Should mention the bad input + at least one valid choice
      expect(msg).toContain("blockchain");
      expect(msg).toMatch(/database|web|search|productivity/);
    });

    it("rejects missing capability field", async () => {
      const { body } = await callTool("find_server", {});
      expect((body as any).error?.code).toBe(-32602);
    });

    it("accepts a valid capability (mocked upstream returns 200)", async () => {
      fetchMock
        .get("https://mcprated.github.io")
        .intercept({ path: /^\/mcprated\/api\/v1\/by-capability\/database\.json\?/ })
        .reply(200, JSON.stringify({ capability: "database", count: 0, servers: [] }), {
          headers: { "content-type": "application/json" },
        });
      const { body } = await callTool("find_server", { capability: "database" });
      expect((body as any).error).toBeUndefined();
    });
  });

  describe("by_kind.kind enum", () => {
    it("rejects kind not in enum", async () => {
      const { body } = await callTool("by_kind", { kind: "platypus" });
      expect((body as any).error?.code).toBe(-32602);
    });

    it("rejects missing kind field", async () => {
      const { body } = await callTool("by_kind", {});
      expect((body as any).error?.code).toBe(-32602);
    });
  });

  describe("top.ranking enum", () => {
    it("rejects ranking not in enum", async () => {
      const { body } = await callTool("top", { ranking: "votes" });
      expect((body as any).error?.code).toBe(-32602);
    });

    it("accepts ranking=composite (default)", async () => {
      fetchMock
        .get("https://mcprated.github.io")
        .intercept({ path: /^\/mcprated\/api\/v1\/top\.json\?/ })
        .reply(200, JSON.stringify({ by_composite: [], by_stars: [], by_recency: [] }), {
          headers: { "content-type": "application/json" },
        });
      const { body } = await callTool("top", {});
      expect((body as any).error).toBeUndefined();
    });
  });

  describe("required-field enforcement", () => {
    it("vet without slug → -32602", async () => {
      const { body } = await callTool("vet", {});
      expect((body as any).error?.code).toBe(-32602);
    });

    it("alternatives without slug → -32602", async () => {
      const { body } = await callTool("alternatives", {});
      expect((body as any).error?.code).toBe(-32602);
    });

    it("server_detail without slug → -32602", async () => {
      const { body } = await callTool("server_detail", {});
      expect((body as any).error?.code).toBe(-32602);
    });
  });

  describe("unknown tool", () => {
    it("returns -32602 with a list of known tools", async () => {
      const { body } = await callTool("nonexistent_tool", {});
      expect((body as any).error?.code).toBe(-32602);
      const msg = ((body as any).error?.message ?? "").toLowerCase();
      expect(msg).toMatch(/find_server|vet|alternatives/);
    });
  });
});
