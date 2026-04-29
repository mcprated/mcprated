# Changelog

All notable changes to the MCPRated rule set are documented here. The format follows [Keep a Changelog](https://keepachangelog.com).

## [v1.3.0] — 2026-04-29 (real Trust signals + 2D verdict)

### Trust axis: 4 → 10 signals

OpenSSF Scorecard imported. Per-repo Scorecard JSON cached in crawler
output (`scorecard` key). Six new Trust signals reading from it:

  - `signed_releases` — Scorecard ≥5/10 (cryptographically signed releases)
  - `pinned_dependencies` — Scorecard ≥7/10 (lockfile pins exact versions)
  - `branch_protection` — Scorecard ≥5/10 (default branch requires review)
  - `token_permissions` — Scorecard ≥7/10 (CI workflows scope minimum)
  - `dependency_update_tool` — Scorecard ≥5/10 (Dependabot/Renovate active)
  - `no_dangerous_workflow` — Scorecard ==10/10 (binary safety check)

Conservative thresholds; missing Scorecard → fail-closed (don't credit).

### Critical CVE hard flag

OSV.dev queried per declared package (npm/PyPI/Cargo). Any HIGH/CRITICAL
open advisory triggers `has_critical_cve` hard flag, capping composite ≤50.
Surfaced in `vet` payload as `hard_flags[]` and (planned) full vulnerability
list under `vulnerabilities` for post-V1.3 work.

### 2D verdict

Replaced 3-bucket verdict (verified | caution | low_quality) with two
orthogonal dimensions, addressing both reviewers' "the 89-and-clean
collapses with the 51-and-flagged into the same `caution` bucket":

  - `quality_tier`: `excellent` (90+) | `solid` (75-89) | `acceptable` (50-74) | `poor` (<50)
  - `flag_status`: `clean` | `caution` (any non-archived flag) | `archived`

Both fields present in `vet` response. Legacy `verdict` derived field kept
for backwards compat. Worker tool description updated.

### Tests

  +14 lint signal tests (Scorecard 6 signals × 2-3 cases + OSV 4 cases)
  +18 render_api verdict tests (quality_tier × 8 buckets, flag_status × 8 cases, render_vet × 2 integration)
  Total: 254 pytest + 55 vitest = 309 tests, all green.

### Deferred (next sessions)

  - Phase K: Sub-server listings for suite repos (awslabs/mcp packages/, modelcontextprotocol/servers src/)
  - Phase M: npm/PyPI registry signals (downloads, deprecation)
  - Phase N: Hierarchical capability taxonomy v2

## [v1.2.0] — 2026-04-29 (cross-LLM-driven trust expansion + recall fixes)

Driven by an architectural review by two independent LLMs (OpenAI Codex source review + Anthropic Opus deep review). 10 systemic findings consensus, 6 fixed this release.

### Trust axis expansion

  - DROPPED: `has_repo_topics` — both reviewers flagged as cosmetic (GitHub
    discoverability proxy, not a trust signal). Trust axis got 33% of its
    weight from a setting that any maintainer can flip in 30 seconds.
  - ADDED: `org_owned` — `repo.owner.type == "Organization"`. Strong prior
    that there's a code review process and the project survives a single
    maintainer departure.
  - ADDED: `has_codeowners` — CODEOWNERS file at root, `.github/`, or `docs/`.
    Triggers GitHub's review-request automation; signals an actual ownership
    model.
  - Trust axis now: license_commercial, has_security_policy, org_owned,
    has_codeowners (4 signals, was 3).
  - V1.3 planned: OpenSSF Scorecard import, OSV.dev advisory hard flag.

### Extraction recall (Python + TypeScript)

  - Python AST extractor now handles **variable-receiver patterns**:
    `my_mcp = FastMCP("X")` followed by `@my_mcp.tool()`. Tracks both
    direct-name decorators (legacy) and runtime-bound MCP class instances.
    Also handles aliased imports (`from x import FastMCP as _MCP`).
    Realistic Python coverage: ~50% → ~85%.
  - TypeScript extractor's Form 2 (object-literal pattern) now walks
    **balanced braces at every nesting depth** instead of disallowing
    nested braces. Real MCP servers ship `inputSchema: { type: 'object', ... }`
    in every tool descriptor — the previous regex silently missed all of
    them. Realistic TS coverage: ~40% → significantly higher.

### tools-index richness

  - `/api/v1/tools-index.json` now carries full per-tool records including
    `description` and `input_keys`, not just `tool_names_preview`. The
    previous `[:10]` cap silently dropped 20+ tools per aggregator.
  - Worker `find_tool` now searches `name + description + input_keys +
    capabilities`, with a 0.3 weight bonus when the query matches the
    tool name itself. Intent-based queries ("read postgres tables") now
    resolve to specific tool names instead of returning empty.

### Bug fixes

  - `render_by_capability` now filters `kind == "server"`. Capability
    shards previously leaked clients/frameworks/tools that happened to
    share a capability tag (Codex finding).
  - taxonomy YAML/Python sync drift test added — fails CI if
    `linter/taxonomy/v1.yaml` and `classify._TAXONOMY` diverge.

### Test infrastructure

  - 207 pytest + 55 vitest = 262 tests, all green on hard CI gate.

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
