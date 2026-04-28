# Contributing to MCPRated

Thanks for your interest. This is a small project; contributions are welcome but please read this first.

## Disagree with a score?

If a server you maintain or use looks wrong in the catalog, the right path is **evidence-first**:

1. Open an issue with the slug (`<owner>__<repo>`) and the specific signal you're disputing.
2. Quote the rule (link to the YAML in `linter/rules/v1.0/`) — what's the rule, what should be true.
3. Show the data — what does the lint actually return for your repo (`/api/v1/vet/<slug>.json`).
4. Propose a fix: "the rule is wrong because…" or "the rule is right but the linter has a bug because…".

We'll respond within a week with one of: rule change, linter fix, or a public explanation of why the existing decision stands. No silent rejections.

## Adding a server to the seed

`tests/regression/seed.txt` is the manually-curated reference list. PRs that add a server need:

- A short justification (what category, why it belongs in Tier A/B/C).
- A first-pass score expectation (run `python3 linter/lint.py --cache .cache --out data` locally and paste the per-axis result in the PR).
- For Tier A entries: a commitment to keep the score above the established baseline. Regression CI will fail PRs that silently drop Tier A scores.

## Code changes

- **TDD is enforced** — every Worker fix and every new linter rule must come with a failing test that demonstrates the bug, then the fix that turns it green. CI rejects deploys when tests are red.
- Run the full suite before pushing:
  ```bash
  pytest                    # 180+ Python tests
  cd worker && npm test     # 50+ TypeScript tests inside workerd runtime
  ```
- Local dev for the Worker:
  ```bash
  cd worker && npm run dev      # localhost:8787
  npx @modelcontextprotocol/inspector@latest http://localhost:8787
  ```

## Rule-set version policy

See `methodology.md`. Adding a signal is a minor bump, threshold changes are major bumps with a public delta report. We don't silently change scoring.

## Code of conduct

Be technical, be specific, be honest about limits of evidence. Personal attacks or harassment get the issue closed.
