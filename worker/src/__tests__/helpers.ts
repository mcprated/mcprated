/**
 * Shared test helpers for Worker tests.
 *
 * We use the `cloudflare:test` SELF fetcher so requests hit the actual
 * exported worker entry, exercising the full pipeline including bindings
 * and Cache API. Upstream fetches are intercepted via `fetchMock` from the
 * same module — that mocks Worker's outbound fetch() to gh-pages.
 */
import { SELF, fetchMock } from "cloudflare:test";

export { SELF, fetchMock };

export const UPSTREAM_BASE = "https://mcprated.github.io/mcprated";

/** Send a JSON-RPC request to the Worker, return parsed JSON response. */
export async function rpc(method: string, params?: unknown, id: number | string = 1) {
  const body: Record<string, unknown> = { jsonrpc: "2.0", id, method };
  if (params !== undefined) body.params = params;
  const res = await SELF.fetch("https://mcp.mcprated.workers.dev/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { status: res.status, body: await res.json() };
}

/** Convenience: invoke a tool by name with arguments. */
export async function callTool(name: string, args?: Record<string, unknown>) {
  const params: Record<string, unknown> = { name };
  if (args !== undefined) params.arguments = args;
  return rpc("tools/call", params, 99);
}

/**
 * Set up a fake gh-pages JSON response. Path is what Worker code fetches —
 * we prefix `/mcprated` to match CATALOG_BASE, and tolerate the cache-buster
 * query string that fetchCatalog appends.
 */
export function mockUpstream(path: string, body: unknown, status = 200) {
  const full = path.startsWith("/mcprated") ? path : `/mcprated${path}`;
  const re = new RegExp(`^${full.replace(/[.\\/]/g, "\\$&")}\\?`);
  fetchMock
    .get("https://mcprated.github.io")
    .intercept({ path: re })
    .reply(status, JSON.stringify(body), {
      headers: { "content-type": "application/json" },
    });
}

/** Force upstream to 404 with a generic HTML page (mimics gh-pages). */
export function mockUpstream404(path: string) {
  const full = path.startsWith("/mcprated") ? path : `/mcprated${path}`;
  const re = new RegExp(`^${full.replace(/[.\\/]/g, "\\$&")}\\?`);
  fetchMock
    .get("https://mcprated.github.io")
    .intercept({ path: re })
    .reply(404, "<!DOCTYPE html><html>404</html>", {
      headers: { "content-type": "text/html" },
    });
}
