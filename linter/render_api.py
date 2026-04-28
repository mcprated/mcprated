#!/usr/bin/env python3
"""MCPRated render_api — generate agent-shaped JSON shards under /api/v1/.

Reads the linted data (data/index.json + data/servers/*.json) and writes
sharded answers an LLM agent can fetch directly:

  /api/v1/manifest.json              - discovery doc, endpoint map, MCP tool defs
  /api/v1/by-capability/<cap>.json   - servers tagged with capability X
  /api/v1/by-kind/<kind>.json        - server / client / framework / tool / ambiguous
  /api/v1/top.json                   - top-by-composite, top-by-stars, top-by-recency
  /api/v1/vet/<slug>.json            - trust-focused subset per server
  /api/v1/alternatives/<slug>.json   - capability-clustered similar servers

Cold-agent friendly: every shard <=10KB; each answers one question; URL pattern
is deterministic so prompts can hard-code it. Stdlib only.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

# Mirrors classify._TAXONOMY keys; static so render_api stays fast (no import).
CAPABILITIES = [
    "database", "filesystem", "web", "search", "productivity", "comms",
    "devtools", "cloud", "ai", "memory", "finance", "media",
]
KINDS = ["server", "client", "framework", "tool", "ambiguous"]
SUBKINDS = ["integration", "aggregator", "prompt-tool", "agent-product"]

TOP_LIMIT = 25
ALTERNATIVES_LIMIT = 10


def _slim(s: dict) -> dict:
    """Project an index entry to the minimum useful for ranking + selection.

    v1.0.1 trims the shape to fight token bloat: nested axes were dropped
    (agents who care about axis breakdown call `vet`), and the relative
    `detail_url` was dropped (agents have the full URL pattern from llms.txt
    or manifest.json — no need to repeat it on every list item). Description
    was added so an agent can disambiguate "supabase-mcp" from "mcp-alchemy"
    without a second roundtrip.
    """
    return {
        "repo": s["repo"],
        "slug": s["slug"],
        "composite": s["composite"],
        "description": s.get("description"),
        "kind": s.get("kind"),
        "subkind": s.get("subkind") or "",
        "capabilities": s.get("capabilities") or [],
        "stars": s.get("stars"),
        "language": s.get("language"),
    }


def _verdict(composite: int, hard_flags: list) -> str:
    """Three-bucket trust verdict for vet endpoint.

    Rules are deliberately simple: agent can override with axis breakdown if
    it disagrees, but most callers want one signal.
    """
    if composite >= 90 and not hard_flags:
        return "verified"
    if composite < 50:
        return "low_quality"
    return "caution"


def _jaccard(a: list, b: list) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------------------
# manifest — what every agent fetches first
# ---------------------------------------------------------------------------

def render_manifest(idx: dict) -> dict:
    """Discovery doc. Agent fetches this once to learn URL templates +
    valid enum values + MCP tool schemas (which the Worker mirrors)."""
    return {
        "version": "1.0",
        "rule_set_version": idx.get("rule_set_version"),
        "taxonomy_version": idx.get("taxonomy_version"),
        "generated_at": idx.get("generated_at"),
        "base_url": "https://mcprated.github.io/mcprated",
        "description": (
            "Agent-readable index of MCP servers. Static JSON, no auth, daily "
            "refresh. Each endpoint answers one question; agents should fetch "
            "the relevant shard rather than the full index.json."
        ),
        "enums": {
            "capabilities": CAPABILITIES,
            "kinds": KINDS,
            "subkinds": SUBKINDS,
        },
        "endpoints": [
            {
                "name": "by_capability",
                "url_template": "/api/v1/by-capability/{capability}.json",
                "params": {"capability": CAPABILITIES + ["unknown"]},
                "description": "Servers tagged with the given capability, ranked by composite score.",
            },
            {
                "name": "by_kind",
                "url_template": "/api/v1/by-kind/{kind}.json",
                "params": {"kind": KINDS},
                "description": "Filter by classifier verdict; default catalog views show kind=server.",
            },
            {
                "name": "top",
                "url": "/api/v1/top.json",
                "description": "Three rankings: by composite, by stars, by recency. Top 25 each.",
            },
            {
                "name": "vet",
                "url_template": "/api/v1/vet/{slug}.json",
                "params": {"slug": "<owner>__<repo>"},
                "description": "Trust-focused subset: composite, axes, license, hard flags, plus a derived verdict (verified / caution / low_quality).",
            },
            {
                "name": "alternatives",
                "url_template": "/api/v1/alternatives/{slug}.json",
                "params": {"slug": "<owner>__<repo>"},
                "description": "Servers with overlapping capabilities, ranked by Jaccard similarity then composite. Up to 10.",
            },
            {
                "name": "server_detail",
                "url_template": "/servers/{slug}.json",
                "params": {"slug": "<owner>__<repo>"},
                "description": "Full lint output for one server: every signal, every reason, every flag.",
            },
            {
                "name": "index",
                "url": "/index.json",
                "description": "The full catalog as one document. Use shards for targeted queries.",
            },
            {
                "name": "excluded",
                "url": "/excluded.json",
                "description": "Repos rejected by prefilter, with reason. Transparency.",
            },
        ],
        "mcp_tools": [
            {
                "name": "find_server",
                "description": "Find MCP servers tagged with a controlled capability category. Use when your need maps to one of the 12 categories; if not, use 'search'.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capability": {"type": "string", "enum": CAPABILITIES + ["unknown"]},
                        "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                    },
                    "required": ["capability"],
                },
            },
            {
                "name": "search",
                "description": "Free-text search when 'find_server' enum doesn't fit. Matches repo name + description + capabilities, ranked by relevance × quality.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 2},
                        "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 25},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "vet",
                "description": "Trust-focused summary of one server: composite, axes, license, hard flags, verdict.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"slug": {"type": "string", "description": "<owner>__<repo>"}},
                    "required": ["slug"],
                },
            },
            {
                "name": "alternatives",
                "description": "Capability-similar servers to a given one, for fallback or comparison.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"slug": {"type": "string"}},
                    "required": ["slug"],
                },
            },
            {
                "name": "by_kind",
                "description": "List servers (or clients / frameworks / tools) by classifier kind.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"kind": {"type": "string", "enum": KINDS}},
                    "required": ["kind"],
                },
            },
            {
                "name": "top",
                "description": "Top servers by composite score, stars, or recency.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ranking": {"type": "string", "enum": ["composite", "stars", "recency"], "default": "composite"},
                        "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 25},
                    },
                },
            },
            {
                "name": "server_detail",
                "description": "Full lint output for one server: every signal pass/fail with reason.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"slug": {"type": "string"}},
                    "required": ["slug"],
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# Sharded views
# ---------------------------------------------------------------------------

def render_by_capability(idx: dict, cap: str) -> dict:
    if cap == "unknown":
        servers = [s for s in idx["servers"] if not (s.get("capabilities") or [])]
    else:
        servers = [s for s in idx["servers"] if cap in (s.get("capabilities") or [])]
    servers.sort(key=lambda s: -s["composite"])
    return {
        "capability": cap,
        "rule_set_version": idx.get("rule_set_version"),
        "taxonomy_version": idx.get("taxonomy_version"),
        "generated_at": idx.get("generated_at"),
        "count": len(servers),
        "servers": [_slim(s) for s in servers],
    }


def render_by_kind(idx: dict, kind: str) -> dict:
    servers = [s for s in idx["servers"] if s.get("kind") == kind]
    servers.sort(key=lambda s: -s["composite"])
    return {
        "kind": kind,
        "rule_set_version": idx.get("rule_set_version"),
        "generated_at": idx.get("generated_at"),
        "count": len(servers),
        "servers": [_slim(s) for s in servers],
    }


def render_top(idx: dict, full_servers: dict[str, dict]) -> dict:
    """Three rankings. Stars and recency need data not in slim index, so we
    pull from per-server JSON when present, else fall back to index."""
    only_servers = [s for s in idx["servers"] if s.get("kind") == "server"]

    by_composite = sorted(only_servers, key=lambda s: -s["composite"])[:TOP_LIMIT]
    by_stars = sorted(only_servers, key=lambda s: -(s.get("stars") or 0))[:TOP_LIMIT]

    def pushed_at(s):
        full = full_servers.get(s["slug"])
        return (full or {}).get("pushed_at") or ""
    by_recency = sorted(only_servers, key=pushed_at, reverse=True)[:TOP_LIMIT]

    return {
        "rule_set_version": idx.get("rule_set_version"),
        "generated_at": idx.get("generated_at"),
        "by_composite": [_slim(s) for s in by_composite],
        "by_stars": [_slim(s) for s in by_stars],
        "by_recency": [_slim(s) for s in by_recency],
    }


def render_vet(idx_entry: dict, full: dict) -> dict:
    """Trust-focused subset. Includes signal-level Trust axis breakdown so an
    agent vetting for production knows exactly which trust signals failed."""
    trust_signals = {}
    trust_axis = (full.get("axes") or {}).get("trust") or {}
    raw_signals = trust_axis.get("signals") or {}
    if isinstance(raw_signals, dict):
        for sig_id, sig in raw_signals.items():
            trust_signals[sig_id] = {
                "passed": bool(sig.get("pass")),
                "note": sig.get("note", ""),
            }

    hard_flags = [f["key"] for f in (full.get("hard_flags") or [])]
    return {
        "repo": full.get("repo"),
        "slug": idx_entry["slug"],
        "rule_set_version": full.get("rule_set_version"),
        "scored_at": full.get("scored_at"),
        "composite": full.get("composite"),
        "axes": {a: (full.get("axes") or {}).get(a, {}).get("score")
                 for a in ("reliability", "documentation", "trust", "community")},
        "kind": full.get("kind"),
        "subkind": full.get("subkind") or "",
        "capabilities": full.get("capabilities") or [],
        "license": full.get("license"),
        "stars": full.get("stars"),
        "pushed_at": full.get("pushed_at"),
        "language": full.get("language"),
        "hard_flags": hard_flags,
        "trust_signals": trust_signals,
        "verdict": _verdict(full.get("composite", 0), hard_flags),
        "url": f"https://github.com/{full.get('repo', '')}",
        "detail_url": f"/servers/{idx_entry['slug']}.json",
    }


def _alt_score(similarity: float, composite: int) -> float:
    """Composite-weighted similarity for alternatives ranking.

    Pure Jaccard (v1.0) ranked junk repos with perfect tag overlap above
    high-quality fallbacks with partial overlap. v1.0.1 multiplies similarity
    by the square root of normalized composite — keeps similarity dominant
    (we still want capability fit) but penalizes low-quality alternatives.

    Examples:
      sim=1.00, comp=30  ->  0.55
      sim=0.67, comp=88  ->  0.63   (preferred — quality fallback)
      sim=0.50, comp=100 ->  0.50
    """
    quality = (max(0, min(100, composite)) / 100.0) ** 0.5
    return similarity * quality


def render_alternatives(idx_entry: dict, all_entries: list) -> dict:
    """Capability-similar servers, weighted by quality.

    For "X is unavailable, what else?" we rank by `_alt_score`: Jaccard
    similarity dominated, but a pure-overlap junk repo loses to a strong
    partial-overlap repo. See _alt_score for the formula and rationale.
    """
    target_caps = idx_entry.get("capabilities") or []
    target_slug = idx_entry["slug"]

    candidates = []
    for s in all_entries:
        if s["slug"] == target_slug:
            continue
        if s.get("kind") != "server":
            continue
        sim = _jaccard(target_caps, s.get("capabilities") or [])
        if sim <= 0:
            continue
        score = _alt_score(sim, s.get("composite", 0))
        candidates.append((score, sim, s))

    candidates.sort(key=lambda x: (-x[0], -x[2]["composite"]))
    return {
        "for": idx_entry["repo"],
        "slug": target_slug,
        "of_capabilities": target_caps,
        "alternatives": [
            {**_slim(s), "similarity": round(sim, 3), "score": round(score, 3),
             "shared_capabilities": sorted(set(target_caps) & set(s.get("capabilities") or []))}
            for score, sim, s in candidates[:ALTERNATIVES_LIMIT]
        ],
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="dir with index.json + servers/")
    ap.add_argument("--out", default="build/site", help="output root (api/v1 will be created under it)")
    args = ap.parse_args()

    data_dir = Path(args.data)
    out_dir = Path(args.out) / "api" / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    idx_path = data_dir / "index.json"
    if not idx_path.exists():
        print(f"ERROR: {idx_path} not found", file=sys.stderr)
        return 1
    idx = json.loads(idx_path.read_text())

    # Load full per-server JSONs; needed for vet (signal breakdown) and top (recency).
    full_servers: dict[str, dict] = {}
    servers_dir = data_dir / "servers"
    if servers_dir.exists():
        for f in servers_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text())
                slug = f.stem
                full_servers[slug] = d
            except Exception as e:
                print(f"  skip {f.name}: {e}", file=sys.stderr)

    written = 0

    # manifest
    (out_dir / "manifest.json").write_text(json.dumps(render_manifest(idx), ensure_ascii=False, indent=2))
    written += 1

    # by-capability
    cap_dir = out_dir / "by-capability"
    cap_dir.mkdir(exist_ok=True)
    for cap in CAPABILITIES + ["unknown"]:
        (cap_dir / f"{cap}.json").write_text(
            json.dumps(render_by_capability(idx, cap), ensure_ascii=False, indent=2)
        )
        written += 1

    # by-kind
    kind_dir = out_dir / "by-kind"
    kind_dir.mkdir(exist_ok=True)
    for kind in KINDS:
        (kind_dir / f"{kind}.json").write_text(
            json.dumps(render_by_kind(idx, kind), ensure_ascii=False, indent=2)
        )
        written += 1

    # top
    (out_dir / "top.json").write_text(
        json.dumps(render_top(idx, full_servers), ensure_ascii=False, indent=2)
    )
    written += 1

    # vet + alternatives — one file per server
    vet_dir = out_dir / "vet"
    vet_dir.mkdir(exist_ok=True)
    alt_dir = out_dir / "alternatives"
    alt_dir.mkdir(exist_ok=True)
    all_entries = idx["servers"]
    for entry in all_entries:
        slug = entry["slug"]
        full = full_servers.get(slug, {"repo": entry["repo"], "composite": entry["composite"], "axes": {}})
        (vet_dir / f"{slug}.json").write_text(
            json.dumps(render_vet(entry, full), ensure_ascii=False, indent=2)
        )
        (alt_dir / f"{slug}.json").write_text(
            json.dumps(render_alternatives(entry, all_entries), ensure_ascii=False, indent=2)
        )
        written += 2

    print(f"render_api: wrote {written} JSON shards to {out_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
