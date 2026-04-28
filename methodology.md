# MCPRated Methodology

This document describes exactly how MCP servers are scored, and — equally important — what we count as an MCP server in the first place. The full ruleset is published as YAML in [`linter/rules/v1.0/`](linter/rules/v1.0). The capability vocabulary is at [`linter/taxonomy/v1.yaml`](linter/taxonomy/v1.yaml). Every score result includes `rule_set_version` and `taxonomy_version` for audit traceability.

## What we catalog

We are agent-first. The catalog must let an LLM agent answer "is this a server", "what does it do", and "should I trust it" without re-reading the README. So we draw the line precisely.

### Operational definition (v1.1)

An **MCP server** is a runnable artifact that implements the Model Context Protocol (stdio / SSE / streamable HTTP), exposes ≥1 of `tools` / `resources` / `prompts`, and is distributed as a product for use by an MCP client.

We do **not** catalog:

- **Frameworks for building MCP servers** — FastMCP, the official `@modelcontextprotocol/sdk`, `mcp-go`, `rmcp`. Tools to build servers, not servers themselves.
- **MCP clients / inspectors / debuggers** — `@modelcontextprotocol/inspector`, MCP-aware UIs, host apps. They consume MCP, they don't expose it.
- **End-user apps that happen to speak MCP** — gemini-cli, n8n, LibreChat, LocalAI. Their primary purpose is something else; MCP support is a feature.
- **Standalone CLIs that don't implement MCP** — a CLI tool that has no MCP surface stays out, even if it's adjacent. (CLIs *wrapped* as MCP servers — `wcgw`, Desktop Commander — are in.)

### kind / subkind classification

Every cataloged repo gets a `kind` and (when `kind=server`) a `subkind`. Both live in per-server JSON and in `index.json`. See [`linter/classify.py`](linter/classify.py) for the deterministic logic.

| `kind` | Meaning |
|---|---|
| `server` | Matches the operational definition above. The thing we actually rate. |
| `client` | MCP host / client / proxy / UI — consumes MCP. |
| `framework` | Library or SDK for building MCP servers. |
| `tool` | Inspector / debugger / dev-tool for MCP. |
| `ambiguous` | Could not classify with confidence — human review may be useful. |

For `kind=server`, `subkind` carries an extra honest signal:

| `subkind` | Meaning | Example |
|---|---|---|
| `integration` | Default. Bridges to an external system or capability. | github, supabase, playwright |
| `aggregator` | Gateway to many sub-tools — one entry hides thousands. | Zapier MCP, Pipedream |
| `prompt-tool` | In-context reasoning aid; no external integration. | sequential-thinking, dice-roller |
| `agent-product` | A product whose MCP surface is one of several. | serena, claude-task-master, awslabs/mcp suite |

Default catalog views and the composite ranking show `kind=server`. `client` / `framework` / `tool` / `ambiguous` are kept in `excluded.json` (auditable) and reachable via planned `/api/v1/by-kind/<kind>.json`.

### Capability taxonomy (v1.0)

Each `kind=server` is tagged with up to 3 `capabilities` from a versioned vocabulary: `database`, `filesystem`, `web`, `search`, `productivity`, `comms`, `devtools`, `cloud`, `ai`, `memory`, `finance`, `media`. Servers matching no keyword get an empty list and surface under `capability=unknown` (deliberate fallback, not an error).

Tagging is heuristic: case-insensitive keyword match against `description + topics + readme[:2000]`. Cheap, deterministic, transparent. Future versions will add AST-extracted tool inventories for finer-grained matching.

Bumping rules: adding a category or keyword is a minor bump (taxonomy v1.1, v1.2, …); renaming or removing is major (v2.0). Server JSON includes `taxonomy_version` so historical data stays interpretable.

### Scope (v1.x)

- **GitHub-hosted only.** Hosted-only / remote MCP endpoints (`mcp.notion.com`, `mcp.linear.app`, etc.) are not crawled in v1.x. We reserve `distribution: hosted` in the schema for a v1.2 ingest pipeline.
- **One repo = one entry.** Mono-repo suites like `awslabs/mcp` and `modelcontextprotocol/servers` are scored at the repo level for v1.x. Sub-server listings are a v1.2 goal.



## Score model

### Per-axis score

Each axis has a fixed set of binary signals (pass/fail). The axis score is:

```
axis_score = round(passing_signals / total_signals × 100)
```

**Why binary signals?** Weighted continuous scoring invites argumentation about weights. Binary signals are auditable, cheap, and add up to a transparent percentage. Each signal is independently testable.

### Composite score

```
composite = round(mean(axis_scores))
```

Equal axis weights. We considered weighted composite (e.g., Hygiene > Community) but rejected it for v1.0 — we don't yet have evidence to defend specific weights.

### Hard flags

Some states cap the composite regardless of signal scores. They surface as separate banners in the UI.

| Flag | Cap | Why |
|---|---:|---|
| `archived` | 30 | Read-only repos are by definition not maintained |
| `disabled` | 30 | Same |
| `fork_low_signal` | 50 | Fork with <5 stars = no traction |
| `empty_description` | 75 | Lazy maintainer signal |
| `weak_description` (only if stars <50) | 80 | Short / placeholder description without community validation |

Stars ≥50 disable `weak_description` cap — community has implicitly endorsed the project.

### Color hints (for UI)

| Range | Color |
|---:|---|
| 90–100 | green |
| 50–89 | yellow |
| 0–49 | red |

These are presentation only; the underlying number is what matters.

## Four axes

The choice of axes maps to four user questions when picking an MCP server:

| Axis | Question | Why this question |
|---|---|---|
| **Reliability** | Will it work and keep working? | First filter: is this even functional? |
| **Documentation** | Can a stranger figure this out? | Determines adoption cost |
| **Trust** | Safe to depend on? | Legal + security positioning |
| **Community** | Are people caring for it? | Predicts long-term viability |

Axis names are an architectural invariant — they will not change in any v1.x. Signals within them can be added/refined/deprecated.

## Signals — v1.0

20 total signals, grouped by axis:

### Reliability (7)

`has_ci` · `no_floating_sdk` · `recently_maintained` · `has_releases` · `tagged_release_recent` · `version_follows_semver` · `release_communication`

### Documentation (5)

`readme_substantive` · `install_instructions` · `tools_documented` · `examples` · `external_docs`

### Trust (3)

`license_commercial` · `has_security_policy` · `has_repo_topics`

### Community (5)

`has_contributing` · `multiple_contributors` · `responsive_issues` · `merged_prs_recent` · `not_solo_initial`

Full definitions: [`linter/rules/v1.0/`](linter/rules/v1.0).

## Versioning policy

### Semver-like rule-set versioning

- **Major** (`1.x → 2.0`) — recalibration. Signal thresholds adjusted, possibly axes rebalanced. Triggered when ecosystem maturity makes v1.x score uninformative (e.g., median composite >90).
- **Minor** (`1.0 → 1.1`) — additive signals. Score scale stays 0–100; existing servers may shift naturally as new "must-have" checks appear.
- **Patch** (`1.0.0 → 1.0.1`) — bug fixes in signal logic without semantic intent change.

### Stability commitments within a major version

Within `v1.x` we commit to:

- 4 axis names unchanged
- Score scale 0–100 unchanged
- Composite formula (mean of axes) unchanged
- Hard flag caps unchanged (or only made stricter, never looser)
- Existing signals never removed without ≥1 minor version of deprecation warning

### Recalibration roadmap

When `v2.0` is released, every existing server gets a transparent **delta report**: "your v1.x score was X, your v2.0 score is Y, here's why." Old `v1.x` rules remain accessible at `?v=1.0` URL parameter for ≥1 year after recalibration, so embedded badges don't break.

## Reference servers

To prevent unintended drift, every rule-set change must pass regression on a fixed set of reference servers (see [`tests/regression/seed.txt`](tests/regression/seed.txt)). These are servers whose grades should be predictable; if a change to a signal flips them unexpectedly, the change needs scrutiny.

Tier A reference (must remain Strong / 80+):
- microsoft/playwright-mcp
- qdrant/mcp-server-qdrant
- supabase-community/supabase-mcp
- modelcontextprotocol/servers
- github/github-mcp-server
- sooperset/mcp-atlassian

## Limits and known biases

- **GitHub-only signals (v1.0)**: If a server is hosted on GitLab/Codeberg/self-hosted, it isn't indexed yet. Multi-platform support is a v1.2 goal.
- **English-language assumptions**: README parsing uses English keywords. Russian/Chinese/Japanese READMEs may underscore on `tools_documented` or `install_instructions`. We're tracking this as a known issue.
- **Mono-repo overview pages**: Mono-repos like `modelcontextprotocol/servers` are scored as one entry. v1.1 will add sub-server listings.
- **Description quality**: Currently a hard flag, not a signal. Cap is conservative.
- **Activity vs quality**: A polished but unmaintained server can still score B+; this is intentional. Documentation and Trust shouldn't decay just because the author moved on.

## Governance

Changes to rules or score model go through:

1. **Issue / discussion** — propose problem + rationale
2. **Draft PR** — YAML rule changes + regression test additions
3. **Public comment** — 14-day window
4. **Validation run** — shadow-mode lint of full catalog, diff report
5. **Merge or reject** — with explicit rationale

This document is authoritative. If code disagrees, code is wrong.

---

*MCPRated rule_set version: 1.1.0 · taxonomy version: 1.0*
