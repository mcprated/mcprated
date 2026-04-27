# MCPRated

Quality ratings for Model Context Protocol servers. Open, daily-updated, deterministic.

**🌐 Live: [mcprated.github.io/mcprated](https://mcprated.github.io/mcprated/)**

Every MCP server on GitHub is lint-checked daily across four axes:

| Axis | Question |
|---|---|
| Reliability | Will it work and keep working? |
| Documentation | Can a stranger figure this out? |
| Trust | Safe to depend on? |
| Community | Are people caring for it? |

Composite 0–100. Open ruleset (MIT). Open data (CC-BY-4.0). Versioned.

## Status

**v0.1 — pre-launch.** 18 reference servers indexed. Daily lint running. Full topic-search crawl, embeddable badges, and search UI shipping in upcoming iterations.

## API

```bash
curl https://mcprated.github.io/mcprated/index.json                          # catalog
curl https://mcprated.github.io/mcprated/servers/<owner>__<repo>.json        # per-server
curl https://mcprated.github.io/mcprated/llms.txt                            # LLM summary
```

Daily snapshots: [Releases](https://github.com/mcprated/mcprated/releases).

## Embed badge in your README

```markdown
[![MCPRated](https://mcprated.github.io/mcprated/badges/<owner>__<repo>.svg)](https://mcprated.github.io/mcprated/)
```

Replace `<owner>__<repo>` with double-underscore-encoded path. Example:

```markdown
[![MCPRated](https://mcprated.github.io/mcprated/badges/microsoft__playwright-mcp.svg)](https://mcprated.github.io/mcprated/)
```

Renders as: ![MCPRated](https://mcprated.github.io/mcprated/badges/microsoft__playwright-mcp.svg)

Badge always reflects the latest score. No URL pinning, no stale embeds.

## Run lint locally

```bash
git clone https://github.com/mcprated/mcprated && cd mcprated
export GITHUB_TOKEN=ghp_...                                # 5000/h authed
python linter/crawler.py --seed tests/regression/seed.txt
python linter/lint.py
```

## Docs

- [methodology.md](methodology.md) — score model, hard flags, versioning policy
- [linter/rules/v1.0/](linter/rules/v1.0/) — open YAML ruleset (4 files, 20 signals)
- [CHANGELOG.md](CHANGELOG.md) — rule-set version history

## License

MIT (code) · CC-BY-4.0 (data in `data/` and release snapshots) · See [LICENSE](LICENSE), [DATA-LICENSE](DATA-LICENSE)
