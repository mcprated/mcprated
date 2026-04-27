# MCPRated Methodology

This document describes exactly how MCP servers are scored. The full ruleset is published as YAML in [`linter/rules/v1.0/`](linter/rules/v1.0). Every score result includes a `rule_set_version` field for audit traceability.

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

*MCPRated rule_set version: 1.0.0*
