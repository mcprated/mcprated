#!/usr/bin/env python3
"""MCPRated linter — 4 axes × 20 signals → composite 0-100.

Agent-first catalog: per-server JSON now also carries `kind`, `subkind`,
`capabilities`, `distribution` (rule_set v1.1.0) so an LLM client can answer
"what does this server do" and "is it actually a server" without re-reading
the README. See `linter/classify.py` and `linter/taxonomy/v1.yaml`.

Axes (rule_set v1.1.0):
  Reliability    Will it work and keep working?
  Documentation  Can a stranger figure this out?
  Trust          Safe to depend on?
  Community      Are people caring for it?

Composite = mean(axis_scores). Hard flags (archived, empty_description, etc.) cap composite.

No deps beyond stdlib. Reads cache JSON written by crawler.py / preload script.
"""
from __future__ import annotations
import base64, json, re, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RULE_SET_VERSION = "1.3.0"
TAXONOMY_VERSION = "1.0"

# Local imports kept after the version constant so external callers that
# `from lint import RULE_SET_VERSION` still work without triggering classify load.
from classify import classify_kind, classify_capabilities  # noqa: E402
from extractor import extract_from_repo, summarize_for_index  # noqa: E402


# =====================================================================
# Prefilter — is this actually an MCP server? (added v1.0.1)
# =====================================================================
#
# Topic-search results often contain repos tagged `mcp-server` / `mcp` that
# are NOT MCP servers (general AI tools, CLIs, libraries). Pass = any of:
#   A) package metadata declares MCP SDK dependency
#   B) README contains MCP config block ("mcpServers" or claude_desktop_config)
#   C) repo description explicitly says "MCP server" or similar
#
# Excluded repos are kept in cache but written to data/excluded/ instead of
# data/servers/, so the index stays clean while the decision is auditable.

_MCP_SDK_HINTS = (
    '@modelcontextprotocol/',          # npm packages
    'modelcontextprotocol-sdk',        # PyPI normalized
    '"mcp"',                           # exact pyproject dep
    "'mcp'",
    'mcp-go',                          # go module convention
    'mark3labs/mcp-go',
    'rmcp',                            # Rust SDK
    'mcp-rs',
    'mcp-sdk',
)

_MCP_DESC_RX = __import__("re").compile(
    r"\b(mcp\s+server|model\s+context\s+protocol|@modelcontextprotocol)\b",
    __import__("re").I,
)


def is_mcp_server(d: dict) -> tuple[bool, str]:
    """Return (is_mcp, reason). Used to filter topic-search false positives.

    Pass = ANY of:
      A) MCP SDK dep across npm / PyPI / Go / Cargo (delegates to classify._has_sdk_dep
         which understands PEP 621 list-style + Poetry + Go imports in source files)
      B) README config block ("mcpServers" or claude_desktop_config)
      C) Description regex match
      D) Source files contain server-run pattern (covers repos that don't pin
         the SDK formally but DO instantiate a server — caught at Layer 2)
      E) Name pattern (widened: *-mcp-*, *-mcp-server, etc.)
    """
    from classify import _has_sdk_dep, _has_run_pattern, _name_matches_mcp

    if _has_sdk_dep(d):
        return True, "sdk_dep"
    readme = d.get("readme", "")
    if '"mcpservers"' in readme.lower() or "claude_desktop_config" in readme.lower():
        return True, "readme_mentions_mcp_config"
    desc = (d["repo"].get("description") or "")
    if _MCP_DESC_RX.search(desc):
        return True, f"description: '{desc[:60]}'"
    if _has_run_pattern(d):
        return True, "server_run_pattern_in_source"
    name = (d["repo"].get("name") or "").lower()
    if _name_matches_mcp(name):
        return True, f"name_pattern: {name}"
    return False, "no MCP SDK dep, no mcpServers in README, no MCP in desc, no server-run pattern, no name match"

GH = "https://api.github.com"
HEADERS = {"User-Agent": "mcprated-linter/0.1", "Accept": "application/vnd.github+json"}


# =====================================================================
# Helpers
# =====================================================================

def _has_top_path(d: dict, *names: str) -> bool:
    paths = [p.lower() for p in (d.get("top_paths") or [])]
    return any(n.lower() in paths for n in names)


PLACEHOLDER_DESCS = (
    "a mcp server", "an mcp server", "the mcp server",
    "mcp server", "model context protocol server",
)

COMMERCIAL_LICENSES = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "MPL-2.0",
    "ISC", "Unlicense", "CC0-1.0", "0BSD",
}


# =====================================================================
# RELIABILITY axis (7 signals) — Will it work and keep working?
# =====================================================================

def s_has_ci(d: dict) -> tuple[bool, str]:
    if d.get("has_ci"):
        return True, "GH Actions workflows present"
    return False, "no .github/workflows/"


def s_no_floating_sdk(d: dict) -> tuple[bool, str]:
    if not d["pkg"]:
        return True, "no package metadata (n/a)"
    raw = "\n".join(d["pkg"].values())
    is_workspace = any(s in raw for s in (
        '"workspaces"', "[tool.uv.workspace]", "[workspace]",
        "pnpm-workspace", '"workspace:*"',
    ))
    patterns = [
        r'["\']?(@modelcontextprotocol/[\w-]+)["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'(?m)^\s*(mcp[\w-]*)\s*=\s*["\']?([^"\'\n]+)["\']?',
        r'(?m)^\s*(modelcontextprotocol[\w-]*)\s*=\s*["\']?([^"\'\n]+)["\']?',
        r'(github\.com/[\w./-]*mcp[\w-]*)\s+([\w.+-]+)',
        r'(rmcp|mcp-rs|mcp-go|mcp-sdk[\w-]*)\s*[=:]\s*["\']?([^"\'\n,]+)',
    ]
    found = []
    for p in patterns:
        for m in re.finditer(p, raw, re.I):
            found.append((m.group(1).strip(), m.group(2).strip()))
    if not found:
        return True, "no MCP SDK dep tracked here (n/a)"
    bad = [(n, v) for n, v in found if v.lower() in ("*", "latest", "")]
    if bad and is_workspace:
        return True, f"workspace mono-repo, {len(bad)} internal `*` deps (ok)"
    if bad:
        return False, f"floating SDK: {bad[0]}"
    return True, f"{len(found)} MCP dep(s), all pinned"


def s_recently_maintained(d: dict) -> tuple[bool, str]:
    pushed = d["repo"].get("pushed_at")
    if not pushed:
        return False, "no pushed_at"
    days = (datetime.now(timezone.utc) - datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days
    return days <= 90, f"pushed {days}d ago"


def s_has_releases(d: dict) -> tuple[bool, str]:
    if d.get("releases_count", 0) > 0:
        return True, f"{d['releases_count']} GH release(s)"
    if d.get("tags_count", 0) > 0:
        return True, f"{d['tags_count']} tag(s) (no GH releases)"
    return False, "no releases, no tags"


def s_tagged_release_recent(d: dict) -> tuple[bool, str]:
    last = d.get("latest_release_date")
    if not last:
        return False, "no GH release"
    days = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
    return days <= 180, f"latest release {days}d ago"


def s_version_follows_semver(d: dict) -> tuple[bool, str]:
    rels = d.get("releases_full") or []
    if not rels:
        return False, "no releases"
    name = (rels[0].get("tag_name") or "").lstrip("v")
    return bool(re.match(r"^\d+\.\d+\.\d+", name)), f"latest tag: {rels[0].get('tag_name')}"


def s_release_communication(d: dict) -> tuple[bool, str]:
    """Pass if CHANGELOG file exists OR ≥ 3 GH releases have substantive notes."""
    if _has_top_path(d, "CHANGELOG.md", "CHANGELOG", "CHANGELOG.rst", "CHANGES.md", "HISTORY.md"):
        return True, "CHANGELOG file present"
    rels = d.get("releases_full") or []
    with_notes = [r for r in rels if len((r.get("body") or "").strip()) >= 80]
    if len(with_notes) >= 3:
        return True, f"{len(with_notes)} releases with notes"
    return False, "no CHANGELOG, no release-notes substitute"


# =====================================================================
# DOCUMENTATION axis (5 signals) — Can a stranger figure this out?
# =====================================================================

def s_readme_substantive(d: dict) -> tuple[bool, str]:
    n = len(d["readme"])
    return n >= 500, f"README {n} chars (need ≥500)"


def s_install_instructions(d: dict) -> tuple[bool, str]:
    r = d["readme"].lower()
    needles = [
        "claude_desktop_config", "mcpservers", '"mcpservers"',
        "npx ", "uvx ", "pip install", "cargo install", "go install", "go get ",
        "docker run", "docker pull", "make install",
        "brew install", "winget install",
        "curl -", "wget ",
    ]
    hit = [n for n in needles if n in r]
    if hit:
        return True, f"needles={hit[:4]}{'…' if len(hit) > 4 else ''}"
    rx = re.compile(
        r"(?im)^#{1,4}\s+(installation|install|setup|quick\s*start|getting\s+started|usage)\b"
    )
    m = rx.search(d["readme"])
    if m:
        section = d["readme"][m.start():m.start() + 1500]
        if len(section) > 200 and ("```" in section or any(
                w in section.lower() for w in ["run", "install", "command", "config"])):
            return True, "install section detected"
    return False, "no install hints, no install section"


def s_tools_documented(d: dict) -> tuple[bool, str]:
    headings = re.findall(r"(?m)^#{1,6}\s+.*", d["readme"])
    rx = re.compile(
        r"^#{1,6}\s+("
        r"tools?|api|available\s+tools?|tool\s+reference|commands?|capabilities|"
        r"features?|what\s+(it\s+does|this\s+does)|functions?|operations?|"
        r"available\s+(commands?|operations?|features?)|reference|methods?"
        r")\b", re.I)
    matched = [h.strip() for h in headings if rx.match(h)]
    if matched:
        return True, f"sections={matched[:3]}"
    code_block_tools = re.findall(
        r'(?:"name"\s*:\s*"[a-z_][\w]*"|^\s*-\s*name:\s*[a-z_])',
        d["readme"], re.M | re.I,
    )
    if len(code_block_tools) >= 3:
        return True, f"{len(code_block_tools)} tool defs in code"
    inline_tools = re.findall(r"`([a-z][a-z0-9_]{3,}(?:_[a-z0-9]+){1,})`", d["readme"])
    if len(set(inline_tools)) >= 5:
        return True, f"{len(set(inline_tools))} unique snake_case identifiers"
    sub_headings = re.findall(r"(?m)^#{2,4}\s+[A-Z][\w./@-]+", d["readme"])
    if len(sub_headings) >= 5:
        return True, f"{len(sub_headings)} sub-sections (overview README)"
    return False, "no Tools/API section, no tool-like patterns"


def s_examples(d: dict) -> tuple[bool, str]:
    blocks = d["readme"].count("```") // 2
    return blocks >= 2, f"{blocks} code blocks"


def s_external_docs(d: dict) -> tuple[bool, str]:
    h = (d["repo"].get("homepage") or "").strip()
    if h:
        return True, f"homepage: {h[:50]}"
    if re.search(r"\[(docs|documentation|website|homepage)\]\(https?://", d["readme"], re.I):
        return True, "docs link in README"
    return False, "no homepage, no docs link"


# =====================================================================
# TRUST axis (3 signals) — Safe to depend on?
# =====================================================================

def s_license_commercial(d: dict) -> tuple[bool, str]:
    """Permissive SPDX OR LICENSE file recognized as known-permissive."""
    spdx = (d["repo"].get("license") or {}).get("spdx_id")
    if spdx in COMMERCIAL_LICENSES:
        return True, f"SPDX={spdx}"
    if d.get("license_text"):
        head = d["license_text"][:600].lower()
        for k in ["mit license", "apache license", "bsd ", "mozilla public", "isc license", "unlicense"]:
            if k in head:
                return True, f"LICENSE file ({k.strip()})"
    if spdx and spdx not in ("NOASSERTION", None):
        return False, f"non-permissive: {spdx}"
    return False, "no commercial-friendly license"


def s_has_security_policy(d: dict) -> tuple[bool, str]:
    if _has_top_path(d, "SECURITY.md", ".github/SECURITY.md"):
        return True, "SECURITY.md present"
    if re.search(r"(?im)^#{1,4}\s+(security|permissions?|auth(entication|orization)?|trust|risk)\b",
                 d["readme"]):
        return True, "security section in README"
    return False, "no SECURITY.md, no security section"


def s_org_owned(d: dict) -> tuple[bool, str]:
    """Organization-owned repo. Strong trust signal.

    G5 (Codex+Opus): Trust axis previously gave 33% weight to has_repo_topics
    (cosmetic). Org-ownership is a much stronger signal — orgs typically have
    review processes, multiple maintainers, and survive single-maintainer
    departure. Personal-account repos can still be excellent (many seed Tier A
    are), but at population level, org ownership shifts the prior.
    """
    owner_type = (d["repo"].get("owner") or {}).get("type") or ""
    if owner_type == "Organization":
        return True, f"owner is an Organization"
    return False, f"owner type: {owner_type or 'unknown'} (not Organization)"


def s_has_codeowners(d: dict) -> tuple[bool, str]:
    """CODEOWNERS file present.

    G5: indicates the repo has a code-review ownership model — even a stub
    CODEOWNERS triggers GitHub's review-request automation. Stronger signal
    than 'has at least 2 topics'.
    """
    paths = [p.lower() for p in (d.get("top_paths") or [])]
    if "codeowners" in paths:
        return True, "CODEOWNERS at root"
    if ".github/codeowners" in paths or "docs/codeowners" in paths:
        return True, "CODEOWNERS at canonical path"
    return False, "no CODEOWNERS file"


# ---------------------------------------------------------------------------
# Phase I-1: OpenSSF Scorecard signals (rule_set v1.3.0)
#
# Scorecard analyzes ~18 security checks per repo, scores each 0-10. We
# adopt 6 checks as Trust signals — these are the ones with highest signal
# density for "should I trust this in production":
#   Signed-Releases, Pinned-Dependencies, Branch-Protection,
#   Token-Permissions, Dependency-Update-Tool, Dangerous-Workflow
#
# Conservative thresholds: pass when Scorecard reports >= 5 (Branch-Protection,
# Signed-Releases, Dependency-Update-Tool) or >= 7 (Pinned-Dependencies,
# Token-Permissions) or == 10 (Dangerous-Workflow — binary safety check).
#
# Missing scorecard → fail-closed. Don't credit repos Scorecard hasn't analyzed.
# ---------------------------------------------------------------------------

def _scorecard_check(d: dict, name: str) -> int | None:
    """Return Scorecard check score by name (0-10), or None if missing."""
    sc = d.get("scorecard")
    if not isinstance(sc, dict):
        return None
    for check in sc.get("checks") or []:
        if isinstance(check, dict) and check.get("name") == name:
            score = check.get("score")
            if isinstance(score, (int, float)):
                return int(score)
    return None


def s_signed_releases(d: dict) -> tuple[bool, str]:
    s = _scorecard_check(d, "Signed-Releases")
    if s is None:
        return False, "no Scorecard data"
    return s >= 5, f"Scorecard Signed-Releases={s}/10"


def s_pinned_dependencies(d: dict) -> tuple[bool, str]:
    s = _scorecard_check(d, "Pinned-Dependencies")
    if s is None:
        return False, "no Scorecard data"
    return s >= 7, f"Scorecard Pinned-Dependencies={s}/10"


def s_branch_protection(d: dict) -> tuple[bool, str]:
    s = _scorecard_check(d, "Branch-Protection")
    if s is None:
        return False, "no Scorecard data"
    return s >= 5, f"Scorecard Branch-Protection={s}/10"


def s_token_permissions(d: dict) -> tuple[bool, str]:
    s = _scorecard_check(d, "Token-Permissions")
    if s is None:
        return False, "no Scorecard data"
    return s >= 7, f"Scorecard Token-Permissions={s}/10"


def s_dependency_update_tool(d: dict) -> tuple[bool, str]:
    s = _scorecard_check(d, "Dependency-Update-Tool")
    if s is None:
        return False, "no Scorecard data"
    return s >= 5, f"Scorecard Dependency-Update-Tool={s}/10"


def s_no_dangerous_workflow(d: dict) -> tuple[bool, str]:
    s = _scorecard_check(d, "Dangerous-Workflow")
    if s is None:
        return False, "no Scorecard data"
    # Binary check: 10 = clean, anything else means a dangerous CI pattern.
    return s == 10, f"Scorecard Dangerous-Workflow={s}/10"


# ---------------------------------------------------------------------------
# Phase I-2: OSV.dev critical CVE hard flag
# ---------------------------------------------------------------------------

def _has_critical_cve_flag(d: dict) -> tuple[str, str] | None:
    """Return (flag_key, message) when any HIGH/CRITICAL OSV advisory is
    associated with the repo's published packages, else None.

    Caps composite at 50 — same severity as `fork_low_signal`. Below the
    `archived` cap of 30 because a maintained-but-vulnerable repo is more
    actionable (patch coming) than an archived one.
    """
    advisories = d.get("osv_advisories") or []
    if not isinstance(advisories, list):
        return None
    critical = [a for a in advisories
                if isinstance(a, dict)
                and (a.get("severity") or "").upper() in ("HIGH", "CRITICAL")]
    if not critical:
        return None
    ids = [a.get("id", "?") for a in critical[:3]]
    pkgs = sorted({a.get("package") for a in critical if a.get("package")})
    detail = f"{len(critical)} open HIGH/CRITICAL advisor{'y' if len(critical)==1 else 'ies'}"
    if pkgs:
        detail += f" ({', '.join(pkgs[:3])})"
    detail += f": {', '.join(ids)}"
    return "has_critical_cve", detail


# =====================================================================
# COMMUNITY axis (5 signals) — Are people caring for it?
# =====================================================================

def s_has_contributing(d: dict) -> tuple[bool, str]:
    if _has_top_path(d, "CONTRIBUTING.md", "CONTRIBUTING.rst", ".github/CONTRIBUTING.md"):
        return True, "CONTRIBUTING file present"
    return False, "no CONTRIBUTING file"


def s_multiple_contributors(d: dict) -> tuple[bool, str]:
    commits = d.get("commits_90d") or []
    authors = {c.get("author", {}).get("login") for c in commits if c.get("author")}
    authors.discard(None)
    return len(authors) >= 2, f"{len(authors)} unique committers in 90d"


def s_responsive_issues(d: dict) -> tuple[bool, str]:
    open_n = d["repo"].get("open_issues_count") or 0
    commits_recent = len(d.get("commits_90d") or [])
    pulls = d.get("closed_pulls_recent") or []
    cutoff = datetime.now(timezone.utc).timestamp() - 90 * 86400
    merged_recent = sum(
        1 for p in pulls
        if p.get("merged_at") and
        datetime.fromisoformat(p["merged_at"].replace("Z", "+00:00")).timestamp() >= cutoff
    )
    if commits_recent >= 10 or merged_recent >= 3:
        return True, f"active: {commits_recent} commits, {merged_recent} merged PRs in 90d"
    if commits_recent == 0:
        return open_n < 5, f"no recent commits, {open_n} open issues"
    ratio = open_n / max(commits_recent, 1)
    return ratio < 5.0, f"{open_n} open / {commits_recent} commits (ratio {ratio:.2f})"


def s_merged_prs_recent(d: dict) -> tuple[bool, str]:
    pulls = d.get("closed_pulls_recent") or []
    if not pulls:
        return False, "no closed PRs"
    cutoff = datetime.now(timezone.utc).timestamp() - 90 * 86400
    merged_recent = sum(
        1 for p in pulls
        if p.get("merged_at") and
        datetime.fromisoformat(p["merged_at"].replace("Z", "+00:00")).timestamp() >= cutoff
    )
    return merged_recent >= 1, f"{merged_recent} merged PR(s) in 90d"


def s_not_solo_initial(d: dict) -> tuple[bool, str]:
    sample = d.get("total_commits_sample") or []
    return len(sample) >= 2, f"≥{len(sample)} commits in history"


# =====================================================================
# Axis registry
# =====================================================================

AXES: dict[str, dict[str, Any]] = {
    "reliability": {
        "question": "Will it work and keep working?",
        "signals": [
            ("has_ci", s_has_ci),
            ("no_floating_sdk", s_no_floating_sdk),
            ("recently_maintained", s_recently_maintained),
            ("has_releases", s_has_releases),
            ("tagged_release_recent", s_tagged_release_recent),
            ("version_follows_semver", s_version_follows_semver),
            ("release_communication", s_release_communication),
        ],
    },
    "documentation": {
        "question": "Can a stranger figure this out?",
        "signals": [
            ("readme_substantive", s_readme_substantive),
            ("install_instructions", s_install_instructions),
            ("tools_documented", s_tools_documented),
            ("examples", s_examples),
            ("external_docs", s_external_docs),
        ],
    },
    "trust": {
        "question": "Safe to depend on?",
        "signals": [
            ("license_commercial", s_license_commercial),
            ("has_security_policy", s_has_security_policy),
            ("org_owned", s_org_owned),
            ("has_codeowners", s_has_codeowners),
            ("signed_releases", s_signed_releases),
            ("pinned_dependencies", s_pinned_dependencies),
            ("branch_protection", s_branch_protection),
            ("token_permissions", s_token_permissions),
            ("dependency_update_tool", s_dependency_update_tool),
            ("no_dangerous_workflow", s_no_dangerous_workflow),
        ],
    },
    "community": {
        "question": "Are people caring for it?",
        "signals": [
            ("has_contributing", s_has_contributing),
            ("multiple_contributors", s_multiple_contributors),
            ("responsive_issues", s_responsive_issues),
            ("merged_prs_recent", s_merged_prs_recent),
            ("not_solo_initial", s_not_solo_initial),
        ],
    },
}


# =====================================================================
# Hard flags (cap composite, surfaced separately in UI)
# =====================================================================

def hard_flags(d: dict) -> list[tuple[str, str]]:
    flags = []
    repo = d["repo"]
    if repo.get("archived"):
        flags.append(("archived", "Repo is archived (read-only)"))
    if repo.get("disabled"):
        flags.append(("disabled", "Repo is disabled"))
    desc = (repo.get("description") or "").strip()
    stars = repo.get("stargazers_count") or 0
    if not desc:
        flags.append(("empty_description", "Repo has no description"))
    elif (len(desc) < 15 or desc.lower() in PLACEHOLDER_DESCS) and stars < 50:
        flags.append(("weak_description", f"Description: '{desc[:40]}' (no community validation)"))
    if repo.get("fork") and stars < 5:
        flags.append(("fork_low_signal", "Fork with no traction"))
    # Phase I-2 (rule_set v1.3): HIGH/CRITICAL OSV advisories on declared
    # packages cap composite at 50 — between fork_low_signal and archived.
    cve_flag = _has_critical_cve_flag(d)
    if cve_flag is not None:
        flags.append(cve_flag)
    return flags


COMPOSITE_CAPS = {
    "archived": 30,
    "disabled": 30,
    "fork_low_signal": 50,
    "has_critical_cve": 50,
    "empty_description": 75,
    "weak_description": 80,
}


def apply_caps(composite: int, flag_keys: set[str]) -> int:
    capped = composite
    for k in flag_keys:
        if k in COMPOSITE_CAPS:
            capped = min(capped, COMPOSITE_CAPS[k])
    return capped


# =====================================================================
# Main lint
# =====================================================================

def lint(repo_data: dict) -> dict:
    """Lint one repo. Input: cache dict from crawler. Output: structured score JSON."""
    out_axes: dict[str, dict] = {}
    for axis_id, axis_def in AXES.items():
        signals_out = {}
        for sig_id, sig_fn in axis_def["signals"]:
            try:
                ok, note = sig_fn(repo_data)
            except Exception as e:
                ok, note = False, f"signal error: {e}"
            signals_out[sig_id] = {"pass": bool(ok), "note": note}
        passing = sum(1 for s in signals_out.values() if s["pass"])
        total = len(signals_out)
        score = round(passing / total * 100) if total else 0
        out_axes[axis_id] = {
            "score": score,
            "passing": passing,
            "total": total,
            "signals": signals_out,
        }
    composite_raw = round(sum(a["score"] for a in out_axes.values()) / len(out_axes))
    flags = hard_flags(repo_data)
    flag_keys = {k for k, _ in flags}
    composite = apply_caps(composite_raw, flag_keys)
    repo = repo_data["repo"]
    kind, subkind, kind_conf, kind_reason = classify_kind(repo_data)
    capabilities = classify_capabilities(repo_data)
    extraction = extract_from_repo(repo_data)
    tools_summary = summarize_for_index(extraction)
    return {
        "repo": f"{repo.get('owner', {}).get('login', repo.get('full_name', '?').split('/')[0])}/{repo.get('name', '?')}",
        "stars": repo.get("stargazers_count"),
        "language": repo.get("language"),
        "license": (repo.get("license") or {}).get("spdx_id"),
        "description": repo.get("description"),
        "pushed_at": repo.get("pushed_at"),
        "kind": kind,
        "subkind": subkind,
        "kind_confidence": kind_conf,
        "kind_reason": kind_reason,
        "capabilities": capabilities,
        "distribution": "repo",
        "taxonomy_version": TAXONOMY_VERSION,
        "tools": tools_summary,
        "tools_extraction": extraction,
        "composite": composite,
        "composite_raw": composite_raw,
        "axes": out_axes,
        "hard_flags": [{"key": k, "msg": m} for k, m in flags],
        "rule_set_version": RULE_SET_VERSION,
        "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# =====================================================================
# Cache I/O (compatible with crawler script outputting one JSON per repo)
# =====================================================================

def load_cache_dir(cache_dir: Path) -> list[dict]:
    out = []
    for f in sorted(cache_dir.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except Exception as e:
            print(f"  skip {f.name}: {e}", file=__import__("sys").stderr)
    return out


def main():
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=".cache", help="dir of cached repo JSONs")
    ap.add_argument("--out", default="data", help="output dir for per-repo lint JSON")
    args = ap.parse_args()

    cache_dir = Path(args.cache)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    servers_dir = out_dir / "servers"
    servers_dir.mkdir(exist_ok=True)
    excluded_dir = out_dir / "excluded"
    excluded_dir.mkdir(exist_ok=True)
    tools_dir = out_dir / "tools"
    tools_dir.mkdir(exist_ok=True)

    repos = load_cache_dir(cache_dir)
    if not repos:
        print(f"No cached repos in {cache_dir}", file=sys.stderr)
        return 1

    index = []
    excluded = []
    for r in repos:
        is_mcp, mcp_reason = is_mcp_server(r)
        repo = r["repo"]
        full_name = f"{repo.get('owner', {}).get('login', '?')}/{repo.get('name', '?')}"
        slug = full_name.replace("/", "__")

        if not is_mcp:
            excluded.append({
                "repo": full_name,
                "slug": slug,
                "reason": "not_mcp_server",
                "detail": mcp_reason,
                "stars": repo.get("stargazers_count"),
                "description": (repo.get("description") or "")[:120],
                "language": repo.get("language"),
            })
            (excluded_dir / f"{slug}.json").write_text(json.dumps({
                "repo": full_name,
                "excluded": True,
                "reason": "not_mcp_server",
                "detail": mcp_reason,
                "rule_set_version": RULE_SET_VERSION,
                "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, ensure_ascii=False, indent=2))
            continue

        result = lint(r)
        # Tools extraction lives in result["tools_extraction"] but is also
        # mirrored to data/tools/<slug>.json for direct agent fetch.
        extraction = result.pop("tools_extraction", None)
        if extraction and extraction.get("source_files_scanned"):
            (tools_dir / f"{slug}.json").write_text(
                json.dumps(extraction, ensure_ascii=False, indent=2)
            )
        (servers_dir / f"{slug}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        index.append({
            "repo": full_name,
            "slug": slug,
            "composite": result["composite"],
            "axes": {a: result["axes"][a]["score"] for a in result["axes"]},
            "stars": result["stars"],
            "language": result["language"],
            "description": result.get("description"),
            "kind": result["kind"],
            "subkind": result["subkind"],
            "capabilities": result["capabilities"],
            "distribution": result["distribution"],
            "tool_count": (result.get("tools") or {}).get("tool_count", 0),
            "tool_names_preview": (result.get("tools") or {}).get("tool_names_preview", []),
            "hard_flags": [f["key"] for f in result["hard_flags"]],
        })
    index.sort(key=lambda x: -x["composite"])
    (out_dir / "index.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rule_set_version": RULE_SET_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "count": len(index),
        "servers": index,
    }, ensure_ascii=False, indent=2))
    (out_dir / "excluded.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rule_set_version": RULE_SET_VERSION,
        "count": len(excluded),
        "reason_summary": "Tagged with mcp-server / mcp topic but failed prefilter (no SDK dep, no mcpServers config in README, no MCP in description/name).",
        "servers": sorted(excluded, key=lambda x: -(x.get("stars") or 0)),
    }, ensure_ascii=False, indent=2))

    # Console summary
    print(f"\nLinted {len(index)} repos, excluded {len(excluded)} (not MCP servers) · rule_set v{RULE_SET_VERSION}")
    print(f"{'Repo':50s} {'Stars':>6} {'Comp':>5} {'Rel':>4} {'Doc':>4} {'Trs':>4} {'Com':>4}  Flags")
    print("-" * 105)
    for r in index[:30]:
        flags = ",".join(r["hard_flags"]) or "-"
        a = r["axes"]
        print(f"{r['repo']:50s} {(r['stars'] or 0):>6} {r['composite']:>5}  "
              f"{a['reliability']:>3} {a['documentation']:>3} {a['trust']:>3} {a['community']:>3}   {flags}")
    if len(index) > 30:
        print(f"... {len(index) - 30} more (full results in {out_dir}/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
