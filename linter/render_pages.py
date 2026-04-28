#!/usr/bin/env python3
"""MCPRated render_pages — generate static HTML landing page from lint data.

V1 minimal: one beautiful, soulful, agent-friendly index.html.
Stdlib only. No Jinja2 / Astro / framework.
"""
from __future__ import annotations
import argparse, html, json, sys
from datetime import datetime, timezone
from pathlib import Path


def _color(score: int) -> str:
    if score >= 90:
        return "good"
    if score >= 50:
        return "ok"
    return "weak"


def _bar(score: int) -> str:
    color = _color(score)
    return f'<div class="bar"><div class="bar-fill bar-{color}" style="width:{score}%"></div></div>'


def render_index(idx: dict, repo_url: str) -> str:
    servers = idx.get("servers", [])
    rule_set = idx.get("rule_set_version", "?")
    generated = idx.get("generated_at", "")
    count = len(servers)

    # Top 10 by composite for the home table
    top = servers[:10]

    # Median / max for context
    composites = [s["composite"] for s in servers]
    median = sorted(composites)[len(composites) // 2] if composites else 0
    perfect = sum(1 for c in composites if c == 100)

    rows = []
    for s in top:
        flags = "".join(
            f'<span class="flag" title="{html.escape(f)}">⚑</span>'
            for f in s.get("hard_flags", [])
        )
        a = s["axes"]
        rows.append(f"""
        <tr>
          <td class="rank">{servers.index(s) + 1}</td>
          <td class="repo">
            <a href="https://github.com/{html.escape(s['repo'])}">{html.escape(s['repo'])}</a>
            {flags}
          </td>
          <td class="composite composite-{_color(s['composite'])}">{s['composite']}</td>
          <td class="axis axis-{_color(a['reliability'])}">{a['reliability']}</td>
          <td class="axis axis-{_color(a['documentation'])}">{a['documentation']}</td>
          <td class="axis axis-{_color(a['trust'])}">{a['trust']}</td>
          <td class="axis axis-{_color(a['community'])}">{a['community']}</td>
          <td class="meta">{html.escape(str(s.get('language') or '—'))} · ★{s.get('stars') or 0:,}</td>
        </tr>""")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MCPRated — Agent-readable index of every MCP server</title>
  <meta name="description" content="Agent-readable index of every MCP server. Built for LLMs to discover, vet, and choose tools at runtime — not for humans to browse. Open ruleset, daily-updated, deterministic.">
  <meta property="og:title" content="MCPRated — agent-first MCP catalog">
  <meta property="og:description" content="Built for LLMs to discover, vet, and choose MCP servers at runtime. Open ruleset, daily-updated, deterministic.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://mcprated.github.io/mcprated/">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="canonical" href="https://mcprated.github.io/mcprated/">
  <link rel="alternate" type="application/json" title="Catalog index (JSON)" href="./index.json">
  <link rel="alternate" type="application/json" title="Agent API manifest" href="./api/v1/manifest.json">
  <link rel="alternate" type="text/plain" title="LLM-friendly summary" href="./llms.txt">
  <style>
    :root {{
      --bg: #0d1117;
      --bg-soft: #161b22;
      --bg-row: #1c2128;
      --fg: #e6edf3;
      --fg-mute: #8b949e;
      --fg-faint: #6e7681;
      --accent: #58a6ff;
      --good: #3fb950;
      --ok: #d29922;
      --weak: #f85149;
      --border: #30363d;
      --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, system-ui, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--sans);
      background: var(--bg);
      color: var(--fg);
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 4rem 1.5rem; }}
    header {{ margin-bottom: 4rem; }}
    .brand {{
      font-family: var(--mono);
      font-size: 1.1rem;
      font-weight: 600;
      letter-spacing: 0.02em;
      color: var(--fg);
      display: inline-block;
      padding: 0.2rem 0.5rem;
      border: 1px solid var(--border);
      border-radius: 4px;
      margin-bottom: 2rem;
    }}
    h1 {{
      font-size: clamp(2rem, 5vw, 3.2rem);
      line-height: 1.1;
      letter-spacing: -0.02em;
      font-weight: 700;
      margin: 0 0 1rem 0;
    }}
    .tagline {{
      font-size: 1.25rem;
      color: var(--fg-mute);
      max-width: 60ch;
      margin: 0 0 2rem 0;
    }}
    .stats {{
      display: flex;
      gap: 2rem;
      flex-wrap: wrap;
      margin-top: 2rem;
      padding-top: 2rem;
      border-top: 1px solid var(--border);
    }}
    .stat {{ font-family: var(--mono); }}
    .stat-num {{ color: var(--fg); font-size: 1.6rem; font-weight: 600; }}
    .stat-label {{ color: var(--fg-faint); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.08em; }}
    section {{ margin: 5rem 0; }}
    h2 {{
      font-size: 1.6rem;
      letter-spacing: -0.01em;
      margin: 0 0 1.5rem 0;
      font-weight: 600;
    }}
    .axes {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1.25rem;
      margin-top: 1.5rem;
    }}
    .axis-card {{
      background: var(--bg-soft);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
    }}
    .axis-card h3 {{
      font-family: var(--mono);
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--accent);
      margin: 0 0 0.5rem 0;
    }}
    .axis-card p {{ margin: 0; color: var(--fg-mute); font-size: 0.95rem; }}
    .axis-card .q {{ color: var(--fg); font-weight: 500; margin-bottom: 0.4rem; }}
    .principle {{
      padding: 1rem 0;
      border-bottom: 1px solid var(--border);
    }}
    .principle:last-child {{ border-bottom: none; }}
    .principle .p-num {{
      font-family: var(--mono);
      color: var(--accent);
      font-size: 0.85rem;
      letter-spacing: 0.05em;
    }}
    .principle .p-text {{ font-size: 1.05rem; margin-top: 0.3rem; }}
    .principle .p-detail {{ color: var(--fg-mute); font-size: 0.95rem; margin-top: 0.4rem; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-family: var(--mono);
      font-size: 0.9rem;
    }}
    thead th {{
      text-align: left;
      padding: 0.6rem 0.5rem;
      color: var(--fg-faint);
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      border-bottom: 1px solid var(--border);
      font-weight: 500;
    }}
    tbody td {{
      padding: 0.6rem 0.5rem;
      border-bottom: 1px solid var(--bg-row);
    }}
    tbody tr:hover {{ background: var(--bg-soft); }}
    td.rank {{ color: var(--fg-faint); width: 1ch; }}
    td.repo a {{ color: var(--fg); text-decoration: none; }}
    td.repo a:hover {{ color: var(--accent); }}
    td.composite {{ font-weight: 600; text-align: right; padding-right: 1rem; }}
    .axis, .composite {{ text-align: right; }}
    .composite-good, .axis-good {{ color: var(--good); }}
    .composite-ok, .axis-ok {{ color: var(--ok); }}
    .composite-weak, .axis-weak {{ color: var(--weak); }}
    td.meta {{ color: var(--fg-faint); font-size: 0.8rem; }}
    .flag {{ color: var(--ok); margin-left: 0.3rem; cursor: help; }}
    .agent-block {{
      background: var(--bg-soft);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.5rem;
      font-family: var(--mono);
      font-size: 0.85rem;
      overflow-x: auto;
    }}
    .agent-block pre {{ margin: 0; color: var(--fg-mute); }}
    .agent-block code {{ color: var(--accent); }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    p {{ max-width: 70ch; }}
    p.lead {{ font-size: 1.05rem; color: var(--fg-mute); }}
    footer {{
      margin-top: 6rem;
      padding-top: 2rem;
      border-top: 1px solid var(--border);
      color: var(--fg-faint);
      font-size: 0.85rem;
      font-family: var(--mono);
    }}
    footer a {{ color: var(--fg-faint); }}
    .links {{
      display: flex;
      gap: 1.5rem;
      flex-wrap: wrap;
      margin-top: 1rem;
      font-family: var(--mono);
      font-size: 0.9rem;
    }}
    .links a {{ color: var(--fg-mute); }}
    .links a:hover {{ color: var(--accent); }}
  </style>
</head>
<body>
<main class="wrap">

<header>
  <span class="brand">mcprated</span>
  <h1>Agent-readable index of<br>every MCP server.</h1>
  <p class="tagline">Built for LLMs to discover, vet, and choose tools at runtime — not for humans to browse. Open ruleset, daily-updated, deterministic. Trust scores today; capability index and <code>@mcprated/mcp-server</code> next.</p>

  <div class="stats">
    <div class="stat">
      <div class="stat-num">{count}</div>
      <div class="stat-label">servers rated</div>
    </div>
    <div class="stat">
      <div class="stat-num">{perfect}</div>
      <div class="stat-label">scoring 100</div>
    </div>
    <div class="stat">
      <div class="stat-num">{median}</div>
      <div class="stat-label">median composite</div>
    </div>
    <div class="stat">
      <div class="stat-num">v{rule_set}</div>
      <div class="stat-label">rule set</div>
    </div>
  </div>
</header>

<section>
  <h2>What we measure</h2>
  <p class="lead">Four axes. Twenty signals. One composite score, 0–100. Each axis answers a single question a developer asks before installing an MCP server.</p>
  <div class="axes">
    <div class="axis-card">
      <h3>Reliability</h3>
      <div class="q">Will it work and keep working?</div>
      <p>CI present, no floating SDK deps, recently maintained, has releases, semver tags, release notes.</p>
    </div>
    <div class="axis-card">
      <h3>Documentation</h3>
      <div class="q">Can a stranger figure this out?</div>
      <p>Substantive README, install instructions, tools documented, code examples, external docs link.</p>
    </div>
    <div class="axis-card">
      <h3>Trust</h3>
      <div class="q">Safe to depend on?</div>
      <p>Commercial-friendly license, security policy, properly tagged for discovery.</p>
    </div>
    <div class="axis-card">
      <h3>Community</h3>
      <div class="q">Are people caring for it?</div>
      <p>Multiple contributors, responsive issues, recent merged PRs, history beyond initial commit, contributing guide.</p>
    </div>
  </div>
</section>

<section>
  <h2>Top 10 today</h2>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Repo</th>
        <th style="text-align:right">Score</th>
        <th style="text-align:right">Rel</th>
        <th style="text-align:right">Doc</th>
        <th style="text-align:right">Trs</th>
        <th style="text-align:right">Com</th>
        <th></th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}
    </tbody>
  </table>
  <p style="margin-top:1.5rem;font-size:0.9rem;color:var(--fg-mute);">
    Full catalog: <a href="./index.json">index.json</a> ·
    Per-server: <a href="./servers/microsoft__playwright-mcp.json">servers/&lt;owner&gt;__&lt;repo&gt;.json</a>
  </p>
</section>

<section>
  <h2>Manifesto</h2>

  <div class="principle">
    <div class="p-num">001 / Open by default</div>
    <div class="p-text">The full ruleset is YAML in a public repo.</div>
    <div class="p-detail">No "trust us" scoring. Anyone can read every signal definition, fork the linter, dispute a result with evidence, propose a change via pull request. Trust comes from auditability, not authority.</div>
  </div>

  <div class="principle">
    <div class="p-num">002 / Deterministic over clever</div>
    <div class="p-text">Twenty binary signals. Same input, same score. Forever.</div>
    <div class="p-detail">No machine-learned weights. No LLM-as-judge in the core score. No popularity contests. A signal either passes or it doesn't, and the rule that decided is published. Reproducibility is the whole point.</div>
  </div>

  <div class="principle">
    <div class="p-num">003 / Versioned, never silently changed</div>
    <div class="p-text">Every score carries the rule-set version that produced it.</div>
    <div class="p-detail">When the bar rises, we tag a new major version, publish a delta report explaining what shifted and why, and keep old versions queryable for at least a year. Embedded badges don't break under your feet.</div>
  </div>

  <div class="principle">
    <div class="p-num">004 / The data is the product</div>
    <div class="p-text">Daily snapshots in GitHub Releases under CC-BY-4.0.</div>
    <div class="p-detail">Pull the JSON, build your own catalog, train your own classifier, embed badges. Attribution is the only ask. The site is the demo; the data is the artifact.</div>
  </div>

  <div class="principle">
    <div class="p-num">005 / Maintainers deserve specifics</div>
    <div class="p-text">Every failed signal links to the exact fix.</div>
    <div class="p-detail">"Score 60 because we don't like you" is a non-answer. We tell you which signal failed, why it failed for your repo specifically, and how to make it pass. Disagreement gets a public reply, never silence.</div>
  </div>
</section>

<section>
  <h2>For agents</h2>
  <p class="lead">MCPRated is built agent-first. The site is a UI; the API is JSON files served from GitHub's CDN. No auth, stable URLs, daily refresh.</p>

  <div class="agent-block">
    <pre><code># Discovery — start here. Lists every endpoint and what it contains.</code>
GET https://mcprated.github.io/mcprated/llms.txt

<code># Catalog index — every server with composite, axes, kind, capabilities, distribution</code>
GET https://mcprated.github.io/mcprated/index.json

<code># Per-server full lint detail (kind, subkind, capabilities, all signal results)</code>
GET https://mcprated.github.io/mcprated/servers/&lt;owner&gt;__&lt;repo&gt;.json

<code># Transparency: what we filtered out and why</code>
GET https://mcprated.github.io/mcprated/excluded.json

<code># Daily snapshot archive (full history)</code>
GET https://github.com/{repo_url}/releases</pre>
  </div>

  <p style="margin-top:1.5rem;color:var(--fg-mute);">
    Each server JSON carries <code>kind</code> (server / client / framework / tool / ambiguous), <code>subkind</code> (integration / aggregator / prompt-tool / agent-product), <code>capabilities[]</code> from a versioned <a href="https://github.com/{repo_url}/blob/main/linter/taxonomy/v1.yaml">taxonomy</a>, and <code>distribution</code>. Use these to answer "what does this server do" and "is it actually a server" without re-reading the README.
  </p>

  <p style="margin-top:1rem;color:var(--fg-mute);">
    Coming next: agent-shaped endpoints (<code>/api/v1/find?capability=…</code>, <code>/vet/&lt;slug&gt;</code>, <code>/by-capability/&lt;cap&gt;.json</code>) and <code>@mcprated/mcp-server</code> as an installable npm package — query the catalog directly from your agent.
  </p>
</section>

<section>
  <h2>Embed your badge</h2>
  <p class="lead">If you maintain an MCP server, drop this into your README. Always reflects the latest score.</p>

  <div class="agent-block">
    <pre><code># Markdown</code>
[![MCPRated](https://mcprated.github.io/mcprated/badges/&lt;owner&gt;__&lt;repo&gt;.svg)](https://mcprated.github.io/mcprated/)

<code># Example: microsoft/playwright-mcp</code>
[![MCPRated](https://mcprated.github.io/mcprated/badges/microsoft__playwright-mcp.svg)](https://mcprated.github.io/mcprated/)</pre>
  </div>

  <p style="margin-top:1.5rem;">
    Renders as:
    <a href="https://mcprated.github.io/mcprated/" style="margin-left:0.5rem;vertical-align:middle;">
      <img src="./badges/microsoft__playwright-mcp.svg" alt="MCPRated badge example" style="vertical-align:middle;">
    </a>
  </p>

  <p style="color:var(--fg-mute);margin-top:1rem;font-size:0.95rem;">
    Replace <code>&lt;owner&gt;__&lt;repo&gt;</code> with your repo path using double underscore as separator (e.g. <code>microsoft__playwright-mcp</code>). The badge auto-updates daily — no URL pinning to maintain.
  </p>
</section>

<section>
  <h2>Status</h2>
  <p>v0.2 — agent-first core. Linter + classifier + capability taxonomy live, daily snapshots running, {count} servers indexed. Coming next: agent-shaped endpoints (<code>find</code>, <code>vet</code>, <code>by-capability</code>) and <code>@mcprated/mcp-server</code> npm package.</p>

  <div class="links">
    <a href="https://github.com/{repo_url}">GitHub →</a>
    <a href="https://github.com/{repo_url}/blob/main/methodology.md">Methodology →</a>
    <a href="https://github.com/{repo_url}/blob/main/CHANGELOG.md">Changelog →</a>
    <a href="https://github.com/{repo_url}/tree/main/linter/rules/v1.0">Ruleset (YAML) →</a>
    <a href="https://github.com/{repo_url}/releases">Snapshot archive →</a>
  </div>
</section>

<footer>
  <div>Generated {generated} · rule_set v{rule_set} · {count} servers</div>
  <div style="margin-top:0.5rem;">Code MIT · Data CC-BY-4.0 · <a href="https://github.com/{repo_url}">github.com/{repo_url}</a></div>
</footer>

</main>
</body>
</html>
"""


def render_llms_txt(idx: dict, repo_url: str) -> str:
    """Anthropic /llms.txt convention — minimal, agent-readable site summary."""
    count = len(idx.get("servers", []))
    rule_set = idx.get("rule_set_version", "?")
    taxonomy = idx.get("taxonomy_version", "1.0")
    generated = idx.get("generated_at", "")
    return f"""# MCPRated

> Agent-readable index of every MCP server. Built for LLMs to discover, vet, and choose tools at runtime — not for humans to browse. Open ruleset, daily-updated, deterministic. We catalog runnable artifacts that implement Model Context Protocol; we do not catalog frameworks for building MCP servers, MCP clients/inspectors, or end-user apps that consume MCP without exposing it.

## Stats

- Servers rated: {count}
- Rule set: v{rule_set}
- Taxonomy: v{taxonomy}
- Last update: {generated}

## API (static JSON, public, free, no auth)

**Start here:**
- [Manifest](https://mcprated.github.io/mcprated/api/v1/manifest.json): endpoint map, valid enum values (capabilities, kinds), MCP tool definitions. **Fetch this first to learn the shape.**

**Sharded answers (one question per file, agent-friendly):**
- `/api/v1/by-capability/<cap>.json` — servers tagged with capability X (database, web, search, ...)
- `/api/v1/by-kind/<kind>.json` — server / client / framework / tool / ambiguous
- `/api/v1/top.json` — top-by-composite, top-by-stars, top-by-recency (25 each)
- `/api/v1/vet/<owner>__<repo>.json` — trust-focused subset + verdict (verified / caution / low_quality)
- `/api/v1/alternatives/<owner>__<repo>.json` — capability-similar servers, ranked

**Full views:**
- [Catalog index](https://mcprated.github.io/mcprated/index.json): every server with composite, axes, `kind`, `subkind`, `capabilities`, `distribution`
- [Per-server detail](https://mcprated.github.io/mcprated/servers/microsoft__playwright-mcp.json): full lint output for one repo (replace path with `<owner>__<repo>.json`)
- [Excluded list](https://mcprated.github.io/mcprated/excluded.json): repos filtered out by prefilter, with reason — transparency
- [Daily snapshot archive](https://github.com/{repo_url}/releases): tarballs of historical state, retained forever

## Per-server fields agents care about

- `kind`: server | client | framework | tool | ambiguous
- `subkind` (when `kind=server`): integration | aggregator | prompt-tool | agent-product
- `capabilities[]`: top tags from taxonomy v{taxonomy}: database, filesystem, web, search, productivity, comms, devtools, cloud, ai, memory, finance, media (or empty if no match)
- `distribution`: how the artifact reaches a client (`repo` for v1; `npm`/`pypi`/`docker`/`hosted` reserved for upcoming ingest)
- `composite` 0–100 + 4 axis scores; `hard_flags[]` for caps (archived → 30, etc.)

## Score model

- 4 axes, each 0–100: Reliability, Documentation, Trust, Community
- Composite = mean of axes
- Hard flags cap composite (archived → 30, empty_description → 75, etc.)
- Color hints: 90+ green, 50–89 yellow, <50 red

## Coming next (planned)

- Agent-shaped endpoints: `/api/v1/find?capability=<cap>`, `/vet/<slug>`, `/by-capability/<cap>.json`, `/api/v1/manifest.json`
- `@mcprated/mcp-server` (npm) — installable MCP server that queries the catalog from your client

## Source

- Repo: https://github.com/{repo_url}
- Methodology + operational definition of "MCP server": https://github.com/{repo_url}/blob/main/methodology.md
- Ruleset (YAML, MIT): https://github.com/{repo_url}/tree/main/linter/rules/v1.0
- Capability taxonomy: https://github.com/{repo_url}/blob/main/linter/taxonomy/v1.yaml
- Changelog: https://github.com/{repo_url}/blob/main/CHANGELOG.md

## License

- Code: MIT
- Data: CC-BY-4.0 (attribution: "Quality data from MCPRated, https://mcprated.github.io/mcprated/")
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="dir containing index.json + servers/")
    ap.add_argument("--templates", default="site/templates", help="(unused for V1, single-file render)")
    ap.add_argument("--out", default="build/site", help="output dir")
    ap.add_argument("--repo-url", default="mcprated/mcprated", help="owner/repo for absolute links")
    args = ap.parse_args()

    data_dir = Path(args.data)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    idx_path = data_dir / "index.json"
    if not idx_path.exists():
        print(f"ERROR: {idx_path} not found", file=sys.stderr)
        return 1
    idx = json.loads(idx_path.read_text())

    # Pages
    (out_dir / "index.html").write_text(render_index(idx, args.repo_url))
    (out_dir / "llms.txt").write_text(render_llms_txt(idx, args.repo_url))

    # Copy raw JSON API into output (so /index.json + /servers/* still work alongside HTML)
    (out_dir / "index.json").write_text(idx_path.read_text())

    # Copy excluded.json if exists (transparency)
    excluded_path = data_dir / "excluded.json"
    if excluded_path.exists():
        (out_dir / "excluded.json").write_text(excluded_path.read_text())
    servers_in = data_dir / "servers"
    servers_out = out_dir / "servers"
    servers_out.mkdir(exist_ok=True)
    if servers_in.exists():
        for f in servers_in.glob("*.json"):
            (servers_out / f.name).write_text(f.read_text())

    # .nojekyll so GH Pages serves files starting with _ etc.
    (out_dir / ".nojekyll").write_text("")

    print(f"Rendered to {out_dir}/", file=sys.stderr)
    print(f"  index.html ({(out_dir / 'index.html').stat().st_size:,} bytes)")
    print(f"  llms.txt ({(out_dir / 'llms.txt').stat().st_size:,} bytes)")
    print(f"  index.json + {len(list(servers_out.glob('*.json')))} per-server JSONs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
