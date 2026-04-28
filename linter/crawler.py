#!/usr/bin/env python3
"""MCPRated crawler — discovers MCP servers and fetches metadata to .cache/.

Discovery sources (in order):
  1. tests/regression/seed.txt — manually curated reference set
  2. GitHub topic search: mcp-server, mcp (when --discover)
  3. Future (V1.1+): npm registry @*/mcp-*, PyPI mcp-*

Auth: requires GITHUB_TOKEN env (5000/h) — unauthenticated 60/h is too low.
"""
from __future__ import annotations
import base64, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

GH = "https://api.github.com"


def _token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def gh_get(path: str, params: dict | None = None) -> dict | list | None:
    url = f"{GH}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "User-Agent": "mcprated-crawler/0.1",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (404, 451):
                return None
            if e.code == 403:
                print(f"  rate-limited or forbidden: {url}", file=sys.stderr)
                return None
            if e.code >= 500 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"  http {e.code} on {url} (giving up)", file=sys.stderr)
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"  network error on {url}: {e} (giving up)", file=sys.stderr)
            return None


def _candidate_source_paths(name: str) -> list[str]:
    """Likely server-entry / tool-definition file paths for a repo.

    Pure function; tested in isolation. Extending this list raises extractor
    coverage but each entry costs one Contents API call when missing.
    """
    pkg = name.replace("-", "_")
    return [
        # TypeScript / JavaScript entry points
        "index.ts", "src/index.ts", "src/server.ts", "src/main.ts",
        "index.js", "src/index.js",
        # Common TS tool-definition layouts (extractor needs these)
        "src/tools.ts", "src/tools/index.ts",
        # Python entry points + package layouts
        "main.py", "server.py", "src/main.py", "src/server.py",
        f"src/{pkg}/server.py", f"src/{pkg}/__main__.py",
        f"src/{pkg}/main.py", f"src/{pkg}/tools.py",
        f"{pkg}/server.py", f"{pkg}/main.py", f"{pkg}/tools.py",
        # Go entry points
        "main.go", "cmd/server/main.go", "server/main.go",
        # Rust
        "src/main.rs", "src/server.rs",
    ]


def fetch_file(owner: str, name: str, path: str) -> str | None:
    data = gh_get(f"/repos/{owner}/{name}/contents/{path}")
    if not data or not isinstance(data, dict) or "content" not in data:
        return None
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch_repo(owner: str, name: str) -> dict | None:
    repo = gh_get(f"/repos/{owner}/{name}")
    if not repo or not isinstance(repo, dict):
        return None

    readme = ""
    rsp = gh_get(f"/repos/{owner}/{name}/readme")
    if rsp and isinstance(rsp, dict) and "content" in rsp:
        try:
            readme = base64.b64decode(rsp["content"]).decode("utf-8", errors="replace")
        except Exception:
            readme = ""

    pkg_meta = {}
    for fn in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "setup.py", "setup.cfg"):
        body = fetch_file(owner, name, fn)
        if body:
            pkg_meta[fn] = body

    # Layer 2 (rule_set v1.1+) — fetch likely server-entry source files so
    # the classifier can detect server-run patterns AND the AST extractor
    # can enumerate registered tools.
    #
    # v1.1.1: also probe tools/ subdirectories — many TS servers split tool
    # defs across src/tools/<feature>.ts, and Python servers across
    # <pkg>/tools/<feature>.py. Without this the extractor misses ~60% of
    # the tools real servers expose.
    source_files: dict[str, str] = {}
    candidates = _candidate_source_paths(name)
    # Soft cap on actual fetches (each costs a Contents API call). Higher
    # than v1.0's 4 — extractor benefits from broader source coverage, and
    # we have ~5000/h authenticated quota.
    fetch_budget = 12
    for path in candidates:
        if len(source_files) >= fetch_budget:
            break
        body = fetch_file(owner, name, path)
        if body:
            source_files[path] = body[:30_000]

    # Tools-directory expansion: if /tools or /src/tools exists, list its
    # contents and pull every file (within budget). This is the single
    # biggest extraction-coverage improvement.
    for tools_dir in ("tools", "src/tools", f"src/{name.replace('-', '_')}/tools"):
        if len(source_files) >= fetch_budget:
            break
        listing = gh_get(f"/repos/{owner}/{name}/contents/{tools_dir}")
        if not isinstance(listing, list):
            continue
        for item in listing:
            if len(source_files) >= fetch_budget:
                break
            if not isinstance(item, dict):
                continue
            ipath = item.get("path") or ""
            if not ipath or ipath in source_files:
                continue
            if not any(ipath.endswith(ext) for ext in (".ts", ".tsx", ".js", ".mjs", ".py", ".go", ".rs")):
                continue
            body = fetch_file(owner, name, ipath)
            if body:
                source_files[ipath] = body[:30_000]

    license_text = None
    spdx = (repo.get("license") or {}).get("spdx_id")
    if spdx == "NOASSERTION":
        for fn in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
            license_text = fetch_file(owner, name, fn)
            if license_text:
                break

    releases = gh_get(f"/repos/{owner}/{name}/releases", {"per_page": 5}) or []
    tags = gh_get(f"/repos/{owner}/{name}/tags", {"per_page": 5}) or []

    tree = gh_get(f"/repos/{owner}/{name}/contents") or []
    top_paths = [item.get("path", "") for item in tree if isinstance(item, dict)]
    has_ci = False
    if ".github" in top_paths:
        wf = gh_get(f"/repos/{owner}/{name}/contents/.github/workflows") or []
        has_ci = isinstance(wf, list) and len(wf) > 0

    since_iso = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    commits_full = gh_get(f"/repos/{owner}/{name}/commits", {"since": since_iso, "per_page": 30}) or []
    commits_90d = [
        {"sha": c.get("sha"),
         "author": {"login": (c.get("author") or {}).get("login")},
         "commit": {"author": {"date": (c.get("commit") or {}).get("author", {}).get("date")}}}
        for c in commits_full if isinstance(c, dict)
    ]
    total_full = gh_get(f"/repos/{owner}/{name}/commits", {"per_page": 2}) or []
    total_commits_sample = [{"sha": c.get("sha")} for c in total_full if isinstance(c, dict)]

    closed_full = gh_get(f"/repos/{owner}/{name}/pulls", {"state": "closed", "per_page": 15}) or []
    closed_pulls_recent = [
        {"number": p.get("number"), "merged_at": p.get("merged_at"), "closed_at": p.get("closed_at")}
        for p in closed_full if isinstance(p, dict)
    ]

    releases_full = [
        {"tag_name": r.get("tag_name"),
         "published_at": r.get("published_at"),
         "body": (r.get("body") or "")[:500]}
        for r in releases if isinstance(r, dict)
    ]

    return {
        "repo": repo,
        "readme": readme,
        "pkg": pkg_meta,
        "source_files": source_files,
        "license_text": license_text,
        "releases_count": len(releases) if isinstance(releases, list) else 0,
        "tags_count": len(tags) if isinstance(tags, list) else 0,
        "latest_release_date": releases[0].get("published_at") if releases else None,
        "has_ci": has_ci,
        "top_paths": top_paths,
        "commits_90d": commits_90d,
        "total_commits_sample": total_commits_sample,
        "closed_pulls_recent": closed_pulls_recent,
        "releases_full": releases_full,
    }


def search_topic(topic: str, limit: int = 100) -> list[str]:
    """Return list of 'owner/name' from GitHub topic search."""
    out: list[str] = []
    page = 1
    while len(out) < limit:
        per_page = min(100, limit - len(out))
        result = gh_get("/search/repositories", {
            "q": f"topic:{topic}",
            "per_page": per_page,
            "page": page,
            "sort": "updated",
            "order": "desc",
        })
        if not result or not isinstance(result, dict):
            break
        items = result.get("items") or []
        if not items:
            break
        out.extend(item["full_name"] for item in items if "full_name" in item)
        if len(items) < per_page:
            break
        page += 1
        if page > 10:
            break
    return out[:limit]


def load_seed(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=".cache", help="output dir for per-repo JSONs")
    ap.add_argument("--seed", default="tests/regression/seed.txt", help="seed list of repos")
    ap.add_argument("--discover", action="store_true",
                    help="also crawl GitHub topic search (mcp-server, mcp)")
    ap.add_argument("--limit", type=int, default=200, help="max repos per topic")
    ap.add_argument("--force", action="store_true", help="re-fetch even if cached")
    args = ap.parse_args()

    cache_dir = Path(args.cache)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if not _token():
        print("WARNING: no GITHUB_TOKEN — unauthenticated rate limit 60/h", file=sys.stderr)

    repos: set[str] = set(load_seed(Path(args.seed)))
    print(f"Seed: {len(repos)} repos")

    if args.discover:
        for topic in ("mcp-server", "mcp"):
            found = search_topic(topic, args.limit)
            print(f"  topic:{topic} → {len(found)} found")
            repos.update(found)

    print(f"Total to fetch: {len(repos)}")
    fetched = 0
    skipped = 0
    for full_name in sorted(repos):
        if "/" not in full_name:
            continue
        owner, name = full_name.split("/", 1)
        cp = cache_dir / f"{owner}__{name}.json"
        if cp.exists() and not args.force:
            skipped += 1
            continue
        print(f"  fetching {full_name}...", file=sys.stderr)
        data = fetch_repo(owner, name)
        if data:
            cp.write_text(json.dumps(data, ensure_ascii=False))
            fetched += 1
        time.sleep(0.3)
    print(f"\nFetched: {fetched}, cached (skipped): {skipped}, total in cache: {len(list(cache_dir.glob('*.json')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
