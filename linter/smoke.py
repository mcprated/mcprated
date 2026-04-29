#!/usr/bin/env python3
"""MCPRated local smoke harness — show what changed, no judgment.

Philosophy: agent-readable diff before/after. The script does NOT decide
what's regression vs intended; it just prints the data and lets the agent
(human or LLM) draw conclusions.

Usage:
    python3 linter/smoke.py                    # run + diff vs last snapshot
    python3 linter/smoke.py --no-diff          # snapshot only, skip diff

Inputs:
    tests/regression/seed.txt  — single source of truth (Tier A/B/C entries)
    .cache/<slug>.json         — shared with full crawl; misses get fetched

Outputs:
    .local/smoke/last.json     — most recent snapshot (overwrite)
    .local/smoke/<ts>.json     — timestamped history (last 10 retained)
    stdout                     — current state table + diff section

Stdlib only. Reuses existing crawler.py and lint.py — same code paths the
daily cron runs, so smoke results are predictive of CI runs.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make linter modules importable as plain `import lint`, etc.
ROOT = Path(__file__).resolve().parent.parent
LINTER = ROOT / "linter"
if str(LINTER) not in sys.path:
    sys.path.insert(0, str(LINTER))

import crawler  # noqa: E402
import lint  # noqa: E402

SEED_PATH = ROOT / "tests" / "regression" / "seed.txt"
CACHE_DIR = ROOT / ".cache"
SMOKE_DIR = ROOT / ".local" / "smoke"
HISTORY_KEEP = 10

# Per-server fields tracked in the snapshot. Anything not listed here is
# ignored by the diff — keep the surface small and stable so noise doesn't
# drown signal.
TRACKED_FIELDS = (
    "composite",
    "kind",
    "subkind",
    "capabilities",
    "tool_count",
    "hard_flags",
    "axes",  # nested dict; diff descends into it as axes.<name>
)


# ---------------------------------------------------------------------------
# Snapshot collection
# ---------------------------------------------------------------------------

def _load_seed(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _ensure_cache(repos: list[str]) -> None:
    """Fetch any seed entries not already in the shared .cache/.
    Same code path the daily cron uses — no duplication."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not crawler._token():
        print("WARN: no GITHUB_TOKEN — unauthenticated rate limit (60/h). "
              "Smoke will succeed only if cache already populated.",
              file=sys.stderr)
    missing = []
    for full_name in repos:
        if "/" not in full_name:
            continue
        owner, name = full_name.split("/", 1)
        slug = f"{owner}__{name}"
        if not (CACHE_DIR / f"{slug}.json").exists():
            missing.append((owner, name, slug))
    if not missing:
        return
    print(f"smoke: cache miss for {len(missing)} repo(s); fetching…", file=sys.stderr)
    import time
    for owner, name, slug in missing:
        print(f"  fetching {owner}/{name}…", file=sys.stderr)
        d = crawler.fetch_repo(owner, name)
        if d:
            (CACHE_DIR / f"{slug}.json").write_text(json.dumps(d, ensure_ascii=False))
        time.sleep(0.3)


def _collect_snapshot(repos: list[str]) -> dict:
    """Run lint over cached entries; project to TRACKED_FIELDS only."""
    by_slug: dict[str, dict] = {}
    for full_name in repos:
        if "/" not in full_name:
            continue
        owner, name = full_name.split("/", 1)
        slug = f"{owner}__{name}"
        cache_file = CACHE_DIR / f"{slug}.json"
        if not cache_file.exists():
            by_slug[slug] = {"slug": slug, "repo": full_name, "_status": "cache_miss"}
            continue
        try:
            cache = json.loads(cache_file.read_text())
        except Exception as e:
            by_slug[slug] = {"slug": slug, "repo": full_name, "_status": f"cache_invalid: {e}"}
            continue
        is_mcp, _reason = lint.is_mcp_server(cache)
        if not is_mcp:
            by_slug[slug] = {
                "slug": slug, "repo": full_name, "_status": "excluded_by_prefilter",
            }
            continue
        result = lint.lint(cache)
        # Project to tracked fields. Axes get flattened to plain int per axis.
        tools_summary = result.get("tools") or {}
        snap_entry = {
            "slug": slug,
            "repo": result.get("repo", full_name),
            "composite": result.get("composite"),
            "kind": result.get("kind"),
            "subkind": result.get("subkind") or "",
            "capabilities": result.get("capabilities") or [],
            "tool_count": tools_summary.get("tool_count", 0),
            "hard_flags": [f["key"] for f in (result.get("hard_flags") or [])],
            "axes": {a: result.get("axes", {}).get(a, {}).get("score")
                     for a in ("reliability", "documentation", "trust", "community")},
        }
        by_slug[slug] = snap_entry
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rule_set_version": lint.RULE_SET_VERSION,
        "taxonomy_version": lint.TAXONOMY_VERSION,
        "servers": by_slug,
    }


# ---------------------------------------------------------------------------
# Diff (pure function — unit-tested in tests/unit/test_smoke.py)
# ---------------------------------------------------------------------------

def _entry_changes(before: dict, after: dict) -> list[tuple[str, object, object]]:
    """Compare two server entries; emit (field, before, after) per changed
    tracked field. Axes get expanded to axes.<name>."""
    out: list[tuple[str, object, object]] = []
    for f in TRACKED_FIELDS:
        if f == "axes":
            b_axes = before.get("axes") or {}
            a_axes = after.get("axes") or {}
            for axis in sorted(set(b_axes) | set(a_axes)):
                if b_axes.get(axis) != a_axes.get(axis):
                    out.append((f"axes.{axis}", b_axes.get(axis), a_axes.get(axis)))
            continue
        b_val = before.get(f)
        a_val = after.get(f)
        # Normalize lists for set-equivalent comparison while preserving repr.
        if isinstance(b_val, list) and isinstance(a_val, list):
            if sorted(b_val) != sorted(a_val):
                out.append((f, b_val, a_val))
            continue
        if b_val != a_val:
            out.append((f, b_val, a_val))
    return out


def _diff_snapshots(before: dict, after: dict) -> dict:
    """Compute structured diff between two snapshots.

    Returns {"new": [slug...], "removed": [slug...],
             "changed": [{"slug": str, "repo": str, "changes": [(field, b, a), ...]}, ...]}

    Pure function: no I/O, no formatting. Stable, sortable, easy to test.
    """
    b_servers = before.get("servers") or {}
    a_servers = after.get("servers") or {}
    b_keys, a_keys = set(b_servers), set(a_servers)

    new = sorted(a_keys - b_keys)
    removed = sorted(b_keys - a_keys)

    changed = []
    for slug in sorted(b_keys & a_keys):
        ch = _entry_changes(b_servers[slug], a_servers[slug])
        if ch:
            changed.append({
                "slug": slug,
                "repo": a_servers[slug].get("repo") or b_servers[slug].get("repo") or slug,
                "changes": ch,
            })
    return {"new": new, "removed": removed, "changed": changed}


# ---------------------------------------------------------------------------
# Rendering — stdout text, agent-readable
# ---------------------------------------------------------------------------

def _fmt_val(v) -> str:
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[" + ",".join(str(x) for x in v) + "]"
    if v is None:
        return "—"
    return str(v)


def _render_snapshot_table(snap: dict) -> str:
    lines = []
    lines.append(f"=== MCPRated smoke run — {snap.get('generated_at', '?')} ===")
    lines.append(
        f"rule_set: v{snap.get('rule_set_version', '?')}  "
        f"taxonomy: v{snap.get('taxonomy_version', '?')}  "
        f"servers: {len(snap.get('servers', {}))}"
    )
    lines.append("")
    lines.append("CURRENT STATE")
    lines.append("─" * 13)
    lines.append(f"{'repo':42s} {'comp':>4} {'kind':10s} {'subkind':14s} {'tools':>5}  capabilities")
    for slug in sorted(snap.get("servers", {}).keys()):
        s = snap["servers"][slug]
        if s.get("_status"):
            lines.append(f"{s.get('repo', slug):42s}  ({s['_status']})")
            continue
        comp = s.get("composite")
        comp_s = "—" if comp is None else f"{comp:4}"
        caps = ",".join(s.get("capabilities") or []) or "—"
        flags = s.get("hard_flags") or []
        flag_s = f"  flags={','.join(flags)}" if flags else ""
        lines.append(
            f"{s.get('repo', slug):42s} {comp_s} "
            f"{(s.get('kind') or '?'):10s} {(s.get('subkind') or '—'):14s} "
            f"{s.get('tool_count', 0):>5}  [{caps}]{flag_s}"
        )
    return "\n".join(lines)


def _render_diff(diff: dict, before_ts: str, after_ts: str) -> str:
    new = diff.get("new") or []
    removed = diff.get("removed") or []
    changed = diff.get("changed") or []

    if not new and not removed and not changed:
        return f"DIFF vs {before_ts} — NO CHANGES"

    lines = []
    lines.append(f"DIFF vs {before_ts}")
    lines.append("─" * 28)

    if changed:
        lines.append(f"CHANGED ({len(changed)}):")
        for c in changed:
            lines.append(f"  {c.get('repo', c['slug'])}:")
            for field, b, a in c["changes"]:
                lines.append(f"    {field:18s} {_fmt_val(b)} → {_fmt_val(a)}")

    if new:
        lines.append("")
        lines.append(f"NEW ({len(new)}):")
        for slug in new:
            lines.append(f"  + {slug}")

    if removed:
        lines.append("")
        lines.append(f"REMOVED ({len(removed)}):")
        for slug in removed:
            lines.append(f"  - {slug}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# History management
# ---------------------------------------------------------------------------

def _prune_history(directory: Path, keep: int = HISTORY_KEEP) -> None:
    """Keep only the most recent `keep` timestamped JSONs.

    Excludes `last.json` from pruning — it's the rolling pointer and lives
    forever. Sort by name, which is ISO-prefixed and therefore time-ordered.
    """
    files = sorted(
        f for f in directory.glob("*.json")
        if f.name != "last.json"
    )
    excess = len(files) - keep
    if excess <= 0:
        return
    for f in files[:excess]:
        try:
            f.unlink()
        except OSError:
            pass


def _save_snapshot(snap: dict) -> Path:
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    ts = snap["generated_at"].replace(":", "-")
    history_path = SMOKE_DIR / f"{ts}.json"
    last_path = SMOKE_DIR / "last.json"
    body = json.dumps(snap, ensure_ascii=False, indent=2)
    history_path.write_text(body)
    last_path.write_text(body)
    _prune_history(SMOKE_DIR, keep=HISTORY_KEEP)
    return history_path


def _load_last_snapshot() -> dict | None:
    p = SMOKE_DIR / "last.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="MCPRated local smoke harness")
    ap.add_argument("--no-diff", action="store_true",
                    help="Don't compare against last.json; just snapshot.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Don't fetch missing repos; lint only what's cached.")
    args = ap.parse_args()

    repos = _load_seed(SEED_PATH)
    if not repos:
        print(f"smoke: empty seed at {SEED_PATH}", file=sys.stderr)
        return 1

    if not args.no_fetch:
        _ensure_cache(repos)

    snapshot = _collect_snapshot(repos)
    print(_render_snapshot_table(snapshot))
    print()

    if not args.no_diff:
        previous = _load_last_snapshot()
        if previous is None:
            print("DIFF — no previous snapshot (first run); next run will compare against this one.")
        else:
            diff = _diff_snapshots(previous, snapshot)
            print(_render_diff(diff, previous.get("generated_at", "?"), snapshot["generated_at"]))

    saved = _save_snapshot(snapshot)
    print(f"\nsaved: {saved.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
