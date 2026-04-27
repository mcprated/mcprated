# MCPRated

**Open quality ratings for Model Context Protocol servers.**

Every MCP server on GitHub, lint-checked daily across four axes:

| Axis | Question |
|---|---|
| **Reliability** | Will it work and keep working? |
| **Documentation** | Can a stranger figure this out? |
| **Trust** | Safe to depend on? |
| **Community** | Are people caring for it? |

Composite score 0–100. Fully open ruleset. Versioned. Regression-tested.

## Status

🚧 **v0.1 — pre-launch.** Linter works locally, daily catalog launching soon at [mcprated.dev](https://mcprated.dev).

## What's here

```
linter/                  Python lint engine + crawler + 4 axes × 20 signals
  rules/v1.0/            YAML signal definitions (open, transparent, versioned)
tests/regression/        Reference seed list of MCP servers
data/                    Generated daily — per-server lint results (JSON)
badges/                  Generated daily — embeddable SVG badges
site/                    Static directory (Jinja2 templates → HTML)
mcp-server/              Future: npm package @mcprated/mcp-server
.github/workflows/       Daily lint cron + Pages deploy
```

## Quickstart (run lint locally)

```bash
git clone https://github.com/mcprated/mcprated
cd mcprated
export GITHUB_TOKEN=ghp_...                # 5000 req/h authed
python linter/crawler.py                   # fetches seed repos to .cache/
python linter/lint.py                      # produces data/index.json + data/servers/*.json
```

Output: `data/index.json` ranked by composite score, `data/servers/<owner>__<repo>.json` per-repo detail.

## Score model (v1.0)

- **Per-axis score** = `passing_signals / total_signals × 100`
- **Composite** = `mean(four axis scores)`
- **Hard flags** cap composite (archived → 30, empty_description → 75, etc.)
- **Color hints**: 90+ green, 50–89 yellow, <50 red

Full methodology: [methodology.md](methodology.md).

## Why open

The whole ruleset is MIT-licensed YAML in [`linter/rules/v1.0/`](linter/rules/v1.0). Anyone can run the linter on their own infrastructure, fork it, propose changes via PR. Trust comes from auditability, not magic.

## Roadmap

- **v1.0** (current) — Phase 1: GitHub repository signals
- **v1.1** — npm/PyPI registry data (download counts, dependents, deprecation)
- **v1.2** — OSV.dev CVE scan, OpenSSF Scorecard integration
- **v2.0** — Manifest validation, runtime sandbox checks (E2B), tool-poisoning detection
- **v2.x** — `@mcprated/mcp-server` npm package (agent-first MCP query tool)

See [CHANGELOG.md](CHANGELOG.md) for rule-set version history.

## Contributing

PRs welcome — especially:
- Adding/refining signals (must include regression tests)
- Reporting false positives/negatives on real servers
- Hosting alternative linter implementations (Go, Rust, JS)

Open an issue first for big changes. RFC process for axis or score-model changes.

## License

- **Code**: MIT — see [LICENSE](LICENSE)
- **Data** (`data/`, `badges/`): CC-BY-4.0 — see [DATA-LICENSE](DATA-LICENSE)
