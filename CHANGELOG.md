# Changelog

All notable changes to the MCPRated rule set are documented here. The format follows [Keep a Changelog](https://keepachangelog.com).

## [v1.1.0] — 2026-04-28 (agent-first core)

Additive — score scale, axes, and composite formula unchanged. Existing `v1.0.0` consumers keep working; new fields are documented and optional from a reader's perspective.

### Definition refinement

Operational definition of "MCP server" rewritten in [methodology.md](methodology.md) with four explicit carve-outs (frameworks for building, clients/inspectors, end-user apps, standalone CLIs). Every cataloged repo is now classified, not silently filtered.

### New per-server fields

- `kind` — `server` | `client` | `framework` | `tool` | `ambiguous`
- `subkind` — `integration` | `aggregator` | `prompt-tool` | `agent-product` (only when `kind=server`)
- `kind_confidence`, `kind_reason` — auditability
- `capabilities[]` — up to 3 tags from versioned taxonomy
- `distribution` — `repo` for v1.x; `npm` / `pypi` / `docker` / `hosted` reserved for upcoming ingest
- `taxonomy_version` — vocabulary version that produced `capabilities[]`

### New artifact: capability taxonomy v1.0

Versioned controlled vocabulary at [`linter/taxonomy/v1.yaml`](linter/taxonomy/v1.yaml). 12 categories: database, filesystem, web, search, productivity, comms, devtools, cloud, ai, memory, finance, media. Heuristic match (case-insensitive substring) against `description + topics + readme[:2000]`.

### New artifact: classifier

[`linter/classify.py`](linter/classify.py) — pure stdlib functions `classify_kind()` and `classify_capabilities()`. Invoked from `lint.py` per repo. Deterministic, auditable, no LLM in the loop.

### Seed expansion

[`tests/regression/seed.txt`](tests/regression/seed.txt) extended with high-adoption MCP servers from 2026-Q2 research (Anthropic Connectors directory, Smithery usage data, Cursor/Codex official docs). Tier C added for borderline kind/subkind cases.

### Messaging

README, landing page, and `/llms.txt` rewritten agent-first. Hero is now "Agent-readable index of every MCP server" rather than "Quality ratings".

## [v1.0.0] — 2026-04-27 (initial)

First public release. 4 axes × 20 signals.

### Axes (architectural invariant for v1.x)

- **Reliability** — Will it work and keep working?
- **Documentation** — Can a stranger figure this out?
- **Trust** — Safe to depend on?
- **Community** — Are people caring for it?

### Signals (20 total)

**Reliability (7):** `has_ci`, `no_floating_sdk`, `recently_maintained`, `has_releases`, `tagged_release_recent`, `version_follows_semver`, `release_communication`

**Documentation (5):** `readme_substantive`, `install_instructions`, `tools_documented`, `examples`, `external_docs`

**Trust (3):** `license_commercial`, `has_security_policy`, `has_repo_topics`

**Community (5):** `has_contributing`, `multiple_contributors`, `responsive_issues`, `merged_prs_recent`, `not_solo_initial`

### Hard flags

- `archived` → composite ≤ 30
- `disabled` → composite ≤ 30
- `fork_low_signal` → composite ≤ 50
- `empty_description` → composite ≤ 75
- `weak_description` (when stars < 50) → composite ≤ 80

### Score model

- Per-axis: `passing / total × 100`
- Composite: `mean(axis scores)`, then capped by hard flags
- Color hints: 90+ green, 50–89 yellow, <50 red

### Reference servers — Tier A (regression baseline)

`microsoft/playwright-mcp`, `qdrant/mcp-server-qdrant`, `supabase-community/supabase-mcp`, `modelcontextprotocol/servers`, `github/github-mcp-server`, `sooperset/mcp-atlassian`

These must score ≥ 80 composite under any future rule-set release in v1.x.

## Future versions (planned)

### [v1.1] — additive signals (target: ~3 months post-launch)

Add to **Trust** axis (currently only 3 signals — broaden):
- `not_archived` (positive signal, complements hard flag)
- `org_owned` (signaling: organizations have stronger guarantees than individuals)
- `signed_releases` (gpg/sigstore — when adoption rises)

Add to **Documentation**:
- `has_quickstart` (separate quickstart from full install)
- `tools_have_descriptions` (each tool has ≥80-char description)

Add cross-axis:
- npm/PyPI registry data: `published_to_registry`, `weekly_downloads_meaningful`, `not_deprecated`, `latest_published_recent`

### [v1.2] — security tier

- OSV.dev CVE integration: `no_known_cves`, `no_severe_advisories`
- OpenSSF Scorecard import (where available)
- Dependency tree health

### [v2.0] — recalibration + manifest tier

Likely raises thresholds, expands axes if needed:
- MCP `mcp.json` manifest convention validation
- Tool description quality (LLM-assisted, opt-in)
- Tool poisoning diff detection (between releases)
- Runtime handshake testing in sandbox

Recalibration delta reports will be published.
