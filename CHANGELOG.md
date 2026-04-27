# Changelog

All notable changes to the MCPRated rule set are documented here. The format follows [Keep a Changelog](https://keepachangelog.com).

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
