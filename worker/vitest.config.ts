import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

// Run tests inside the actual workerd runtime so caches.default, fetch,
// ExecutionContext etc. all behave like production. The pool spins up an
// isolate per test file by default.
export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        wrangler: { configPath: "./wrangler.toml" },
        // Per-test-isolate so cache state from one test doesn't leak to another.
        isolatedStorage: true,
      },
    },
    include: ["src/**/*.test.ts", "src/__tests__/**/*.test.ts"],
  },
});
