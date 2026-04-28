import { describe, it, expect } from "vitest";
import { rpc, SELF } from "./helpers";

describe("MCP handshake", () => {
  it("GET / returns plain-text friendly index", async () => {
    const res = await SELF.fetch("https://mcp.mcprated.workers.dev/");
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).toContain("MCPRated MCP server");
    expect(text).toContain("tools/list");
  });

  it("OPTIONS returns 204 with CORS headers", async () => {
    const res = await SELF.fetch("https://mcp.mcprated.workers.dev/", { method: "OPTIONS" });
    expect(res.status).toBe(204);
    expect(res.headers.get("access-control-allow-origin")).toBe("*");
  });

  it("initialize returns protocol version + serverInfo", async () => {
    const { body } = await rpc("initialize");
    expect(body).toMatchObject({
      jsonrpc: "2.0",
      id: 1,
      result: {
        protocolVersion: expect.any(String),
        capabilities: { tools: {} },
        serverInfo: { name: "mcprated" },
      },
    });
  });

  it("tools/list returns the seven declared tools", async () => {
    const { body } = await rpc("tools/list");
    const result = (body as any).result;
    const names = result.tools.map((t: any) => t.name).sort();
    expect(names).toEqual([
      "alternatives",
      "by_kind",
      "find_server",
      "search",
      "server_detail",
      "top",
      "vet",
    ]);
  });

  it("each tool has an inputSchema with type=object", async () => {
    const { body } = await rpc("tools/list");
    for (const tool of (body as any).result.tools) {
      expect(tool.inputSchema?.type).toBe("object");
    }
  });

  it("ping returns empty result", async () => {
    const { body } = await rpc("ping");
    expect((body as any).result).toEqual({});
  });

  it("unknown method returns -32601", async () => {
    const { body } = await rpc("nonsense/method");
    expect((body as any).error?.code).toBe(-32601);
  });

  it("malformed JSON returns -32700", async () => {
    const res = await SELF.fetch("https://mcp.mcprated.workers.dev/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{not json",
    });
    const body = await res.json();
    expect((body as any).error?.code).toBe(-32700);
  });

  it("wrong jsonrpc version returns -32600", async () => {
    const res = await SELF.fetch("https://mcp.mcprated.workers.dev/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "1.0", id: 1, method: "ping" }),
    });
    const body = await res.json();
    expect((body as any).error?.code).toBe(-32600);
  });

  it("notifications (no id) → 202 no body", async () => {
    const res = await SELF.fetch("https://mcp.mcprated.workers.dev/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }),
    });
    expect(res.status).toBe(202);
  });
});
