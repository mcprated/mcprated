import { describe, it, expect } from "vitest";

// Smallest possible test to verify vitest + workers pool wiring.
// If this can't even run, nothing else can — keep it dumb on purpose.
describe("sanity", () => {
  it("runs inside workerd runtime", () => {
    expect(typeof caches.default).toBe("object");
    expect(typeof Response).toBe("function");
  });
});
