"""Tests for render_api — the agent-shaped JSON shards under /api/v1/.

Failing tests pin known bugs (Bug #4 payload slim, Bug #5 alternatives ranking).
"""
from __future__ import annotations
import pytest

import render_api


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_index_entry(**overrides):
    base = {
        "repo": "acme/foo",
        "slug": "acme__foo",
        "composite": 80,
        "axes": {"reliability": 80, "documentation": 80, "trust": 80, "community": 80},
        "stars": 100,
        "language": "TypeScript",
        "kind": "server",
        "subkind": "integration",
        "capabilities": ["database"],
        "distribution": "repo",
        "hard_flags": [],
    }
    base.update(overrides)
    return base


def make_index(*entries, version="1.1.0", taxonomy="1.0"):
    return {
        "rule_set_version": version,
        "taxonomy_version": taxonomy,
        "generated_at": "2026-04-28T00:00:00+00:00",
        "count": len(entries),
        "servers": list(entries),
    }


# ---------------------------------------------------------------------------
# _slim — list-payload projection
# ---------------------------------------------------------------------------

class TestSlim:
    def test_slim_keeps_required_fields(self):
        entry = make_index_entry()
        result = render_api._slim(entry)
        for key in ("repo", "slug", "composite", "kind", "capabilities", "stars"):
            assert key in result, f"missing required key {key} in slim output"

    def test_slim_handles_missing_optional_fields(self):
        entry = make_index_entry(language=None, kind=None, subkind=None)
        result = render_api._slim(entry)
        # Should not crash; optional fields just None/empty.
        assert result["repo"] == "acme/foo"


class TestSlimPayloadShape:
    """Bug #4 fix (v1.0.1): list payloads dropped nested axes + relative
    detail_url. Description was added so agents can disambiguate without a
    second roundtrip.
    """

    def test_slim_does_not_include_nested_axes(self):
        result = render_api._slim(make_index_entry())
        assert "axes" not in result, (
            f"_slim should not return nested axes — that's for /api/v1/vet. Got: {list(result.keys())}"
        )

    def test_slim_does_not_include_relative_detail_url(self):
        result = render_api._slim(make_index_entry())
        # Either absent or absolute. We chose absent — agents have llms.txt
        # for the URL pattern.
        if "detail_url" in result:
            assert result["detail_url"].startswith("http"), (
                f"detail_url must be absolute or absent. Got: {result['detail_url']!r}"
            )

    def test_slim_includes_description(self):
        # Bug #4: agents need description to disambiguate "supabase" from
        # "mcp-alchemy" without fetching server_detail.
        entry = make_index_entry(description="An MCP for Postgres + Supabase")
        result = render_api._slim(entry)
        assert "description" in result
        assert "Supabase" in result["description"]


# ---------------------------------------------------------------------------
# _verdict — trust verdict bucketing
# ---------------------------------------------------------------------------

class TestVerdict:
    @pytest.mark.parametrize("composite, flags, expected", [
        (100, [],            "verified"),
        (90,  [],            "verified"),
        (89,  [],            "caution"),
        (50,  [],            "caution"),
        (49,  [],            "low_quality"),
        (0,   [],            "low_quality"),
        (95,  ["archived"],  "caution"),    # any flag downgrades from verified
        (95,  ["empty_description"], "caution"),
        (40,  ["archived"],  "low_quality"), # low score wins over flag
    ])
    def test_verdict_buckets(self, composite, flags, expected):
        # Backwards-compat: legacy 3-bucket verdict still derived correctly.
        assert render_api._verdict(composite, flags) == expected


class TestVerdict2D:
    """Phase I-3: 2D verdict — quality_tier × flag_status. The legacy 3-bucket
    verdict was too coarse: composite 89 with no flags collapsed into the
    same `caution` as composite 51 with weak_description. Agents lost
    actionable distinction.

    Quality tiers:  excellent (90+) | solid (75-89) | acceptable (50-74) | poor (<50)
    Flag statuses:  clean | caution (any non-archived hard_flag) | archived (special)
    """

    @pytest.mark.parametrize("composite, expected", [
        (100, "excellent"),
        (90,  "excellent"),
        (89,  "solid"),
        (75,  "solid"),
        (74,  "acceptable"),
        (50,  "acceptable"),
        (49,  "poor"),
        (0,   "poor"),
    ])
    def test_quality_tier(self, composite, expected):
        assert render_api._quality_tier(composite) == expected

    @pytest.mark.parametrize("flags, expected", [
        ([], "clean"),
        (["empty_description"], "caution"),
        (["weak_description"], "caution"),
        (["fork_low_signal"], "caution"),
        (["has_critical_cve"], "caution"),
        (["archived"], "archived"),  # archived gets its own bucket
        (["disabled"], "archived"),  # disabled is the same end-state
        (["archived", "empty_description"], "archived"),  # archived dominates
    ])
    def test_flag_status(self, flags, expected):
        assert render_api._flag_status(flags) == expected

    def test_render_vet_includes_both_dimensions(self):
        full = {
            "repo": "x/y",
            "composite": 92,
            "axes": {
                "reliability": {"score": 90}, "documentation": {"score": 90},
                "trust": {"score": 90}, "community": {"score": 90},
            },
            "hard_flags": [],
        }
        entry = make_index_entry(slug="x__y", composite=92)
        result = render_api.render_vet(entry, full)
        assert result["quality_tier"] == "excellent"
        assert result["flag_status"] == "clean"
        # Legacy verdict still present for backwards compat
        assert result["verdict"] == "verified"

    def test_render_vet_archived_dominates(self):
        # In the real pipeline, hard_flag caps are applied before render_vet
        # runs, so full.composite is already the post-cap value (30 for archived).
        full = {
            "repo": "x/y", "composite": 30,  # post-cap from archived flag
            "axes": {a: {"score": 90} for a in
                     ("reliability", "documentation", "trust", "community")},
            "hard_flags": [{"key": "archived", "msg": "..."}],
        }
        entry = make_index_entry(slug="x__y", composite=30)
        result = render_api.render_vet(entry, full)
        assert result["flag_status"] == "archived"
        assert result["quality_tier"] == "poor"


# ---------------------------------------------------------------------------
# _jaccard — capability similarity
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical_sets(self):
        assert render_api._jaccard(["a", "b"], ["a", "b"]) == 1.0

    def test_disjoint_sets(self):
        assert render_api._jaccard(["a"], ["b"]) == 0.0

    def test_one_overlap_two_each(self):
        # |{a,b} ∩ {b,c}| / |{a,b,c}| = 1/3
        assert render_api._jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1/3)

    def test_empty_sets_safe(self):
        assert render_api._jaccard([], []) == 0.0
        assert render_api._jaccard(["a"], []) == 0.0
        assert render_api._jaccard([], ["a"]) == 0.0

    def test_duplicates_collapse(self):
        # ["a", "a"] is treated as set {a}
        assert render_api._jaccard(["a", "a"], ["a"]) == 1.0


# ---------------------------------------------------------------------------
# render_manifest
# ---------------------------------------------------------------------------

class TestManifest:
    def test_manifest_has_required_top_keys(self):
        m = render_api.render_manifest(make_index())
        for key in ("version", "rule_set_version", "taxonomy_version", "endpoints", "enums", "mcp_tools"):
            assert key in m, f"manifest missing {key}"

    def test_manifest_enums_match_constants(self):
        m = render_api.render_manifest(make_index())
        assert set(m["enums"]["capabilities"]) == set(render_api.CAPABILITIES)
        assert set(m["enums"]["kinds"]) == set(render_api.KINDS)
        assert set(m["enums"]["subkinds"]) == set(render_api.SUBKINDS)

    def test_manifest_lists_all_eight_tools(self):
        m = render_api.render_manifest(make_index())
        names = {t["name"] for t in m["mcp_tools"]}
        assert names == {
            "find_server", "find_tool", "search", "vet",
            "alternatives", "by_kind", "top", "server_detail",
        }

    def test_every_tool_has_input_schema(self):
        m = render_api.render_manifest(make_index())
        for t in m["mcp_tools"]:
            assert "inputSchema" in t, f"tool {t['name']} missing inputSchema"
            assert t["inputSchema"]["type"] == "object"


# ---------------------------------------------------------------------------
# render_by_capability — filtering correctness
# ---------------------------------------------------------------------------

class TestByCapability:
    def test_filters_to_capability(self):
        idx = make_index(
            make_index_entry(slug="a", capabilities=["database"], composite=90),
            make_index_entry(slug="b", capabilities=["web"], composite=85),
            make_index_entry(slug="c", capabilities=["database", "ai"], composite=70),
        )
        result = render_api.render_by_capability(idx, "database")
        assert result["count"] == 2
        slugs = {s["slug"] for s in result["servers"]}
        assert slugs == {"a", "c"}

    def test_sorted_by_composite_desc(self):
        idx = make_index(
            make_index_entry(slug="low", capabilities=["database"], composite=40),
            make_index_entry(slug="hi",  capabilities=["database"], composite=95),
            make_index_entry(slug="mid", capabilities=["database"], composite=70),
        )
        result = render_api.render_by_capability(idx, "database")
        composites = [s["composite"] for s in result["servers"]]
        assert composites == sorted(composites, reverse=True)

    def test_unknown_returns_servers_with_empty_capabilities(self):
        idx = make_index(
            make_index_entry(slug="tagged", capabilities=["database"]),
            make_index_entry(slug="untagged", capabilities=[]),
        )
        result = render_api.render_by_capability(idx, "unknown")
        assert result["count"] == 1
        assert result["servers"][0]["slug"] == "untagged"

    def test_only_kind_server_returned(self):
        # G1 (Codex finding): manifest text says by_capability returns
        # "Servers tagged with given capability" but render_by_capability
        # was filtering only by tag, not by kind. Clients/frameworks/tools
        # tagged with the same capability would leak through.
        idx = make_index(
            make_index_entry(slug="real-server", kind="server", capabilities=["database"]),
            make_index_entry(slug="some-client", kind="client", capabilities=["database"]),
            make_index_entry(slug="a-framework", kind="framework", capabilities=["database"]),
            make_index_entry(slug="a-tool", kind="tool", capabilities=["database"]),
            make_index_entry(slug="ambiguous-thing", kind="ambiguous", capabilities=["database"]),
        )
        result = render_api.render_by_capability(idx, "database")
        slugs = {s["slug"] for s in result["servers"]}
        assert slugs == {"real-server"}, (
            f"by_capability must only return kind=server. Got: {slugs}"
        )
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# render_by_kind — filtering by classifier kind
# ---------------------------------------------------------------------------

class TestByKind:
    def test_filters_by_kind(self):
        idx = make_index(
            make_index_entry(slug="s1", kind="server"),
            make_index_entry(slug="c1", kind="client"),
            make_index_entry(slug="f1", kind="framework"),
        )
        for kind, expected in [("server", {"s1"}), ("client", {"c1"}), ("framework", {"f1"})]:
            result = render_api.render_by_kind(idx, kind)
            assert {s["slug"] for s in result["servers"]} == expected


# ---------------------------------------------------------------------------
# render_top — three rankings, server-only
# ---------------------------------------------------------------------------

class TestTop:
    def test_only_servers_in_rankings(self):
        idx = make_index(
            make_index_entry(slug="s", kind="server", composite=80, stars=100),
            make_index_entry(slug="c", kind="client", composite=95, stars=200),
        )
        full = {}
        result = render_api.render_top(idx, full)
        for ranking in ("by_composite", "by_stars", "by_recency"):
            slugs = {s["slug"] for s in result[ranking]}
            assert "c" not in slugs, f"client leaked into {ranking}"

    def test_rankings_have_top_limit(self):
        # Build 50 servers with varying composites
        entries = [
            make_index_entry(slug=f"s{i}", composite=100 - i, stars=i * 10)
            for i in range(50)
        ]
        idx = make_index(*entries)
        result = render_api.render_top(idx, {})
        assert len(result["by_composite"]) <= render_api.TOP_LIMIT
        assert len(result["by_stars"]) <= render_api.TOP_LIMIT


# ---------------------------------------------------------------------------
# render_vet — trust subset + verdict
# ---------------------------------------------------------------------------

class TestVet:
    def test_vet_includes_verdict(self):
        full = {
            "repo": "acme/foo", "composite": 95,
            "axes": {"reliability": {"score": 100}, "documentation": {"score": 100},
                     "trust": {"score": 80, "signals": {"license_commercial": {"pass": True}}},
                     "community": {"score": 100}},
            "license": "MIT", "stars": 1000,
            "pushed_at": "2026-04-01T00:00:00Z",
            "kind": "server", "subkind": "integration",
            "capabilities": ["database"],
            "hard_flags": [],
            "rule_set_version": "1.1.0",
        }
        entry = make_index_entry(slug="acme__foo", composite=95)
        result = render_api.render_vet(entry, full)
        assert result["verdict"] == "verified"
        assert result["composite"] == 95

    def test_vet_axes_flattened_to_score(self):
        full = {
            "repo": "x/y", "composite": 80,
            "axes": {"reliability": {"score": 80}, "documentation": {"score": 80},
                     "trust": {"score": 80}, "community": {"score": 80}},
            "hard_flags": [],
        }
        entry = make_index_entry(slug="x__y")
        result = render_api.render_vet(entry, full)
        # axes should be {axis_name: int}, not {axis_name: {score: int}}
        for axis in ("reliability", "documentation", "trust", "community"):
            assert isinstance(result["axes"][axis], int), (
                f"axes.{axis} should be flat int. Got: {result['axes'][axis]!r}"
            )


# ---------------------------------------------------------------------------
# render_alternatives — Jaccard ranking
# ---------------------------------------------------------------------------

class TestAlternatives:
    def test_skips_self(self):
        idx_servers = [
            make_index_entry(slug="self", capabilities=["database"]),
            make_index_entry(slug="other", capabilities=["database"]),
        ]
        target = idx_servers[0]
        result = render_api.render_alternatives(target, idx_servers)
        slugs = {a["slug"] for a in result["alternatives"]}
        assert "self" not in slugs

    def test_skips_non_server_kinds(self):
        idx_servers = [
            make_index_entry(slug="me", capabilities=["database"]),
            make_index_entry(slug="cli", kind="client", capabilities=["database"]),
        ]
        result = render_api.render_alternatives(idx_servers[0], idx_servers)
        slugs = {a["slug"] for a in result["alternatives"]}
        assert "cli" not in slugs

    def test_no_overlap_returns_empty(self):
        idx_servers = [
            make_index_entry(slug="me", capabilities=["database"]),
            make_index_entry(slug="other", capabilities=["web"]),
        ]
        result = render_api.render_alternatives(idx_servers[0], idx_servers)
        assert result["alternatives"] == []


class TestExpandSubServers:
    """Phase K2: pure function that takes an index + full per-server JSONs
    and returns an extended index with one virtual entry per detected
    sub-server (inheriting parent composite/license, own capabilities/tools)."""

    def _full_with_subs(self, slug, sub_servers):
        return {
            "repo": slug.replace("__", "/"),
            "kind": "server", "subkind": "agent-product",
            "composite": 90,
            "capabilities": ["devtools"],
            "license": "Apache-2.0",
            "language": "Python",
            "stars": 8000,
            "sub_servers": sub_servers,
        }

    def test_no_subs_returns_unchanged_index(self):
        idx = make_index(make_index_entry(slug="x__a"))
        full = {"x__a": {"sub_servers": []}}
        out = render_api._expand_sub_servers(idx, full)
        assert len(out["servers"]) == 1
        assert out["servers"][0]["slug"] == "x__a"

    def test_sub_servers_appended_as_virtual_entries(self):
        idx = make_index(make_index_entry(slug="awslabs__mcp", repo="awslabs/mcp",
                                          kind="server", subkind="agent-product",
                                          composite=94, capabilities=["devtools", "cloud"]))
        full = {"awslabs__mcp": self._full_with_subs("awslabs__mcp", [
            {"name": "dynamodb-mcp-server", "subpath": "packages/dynamodb-mcp-server",
             "tools_count": 3, "tools": [
                 {"name": "get_item", "description": "Get DynamoDB item", "input_keys": ["table"]},
             ],
             "extraction_method": "ast_python"},
            {"name": "s3-mcp-server", "subpath": "packages/s3-mcp-server",
             "tools_count": 2, "tools": [
                 {"name": "list_buckets", "description": "List S3 buckets", "input_keys": []},
             ],
             "extraction_method": "ast_python"},
        ])}
        out = render_api._expand_sub_servers(idx, full)
        slugs = sorted(s["slug"] for s in out["servers"])
        assert slugs == ["awslabs__mcp", "awslabs__mcp__dynamodb-mcp-server",
                         "awslabs__mcp__s3-mcp-server"]

    def test_virtual_entry_has_parent_slug_field(self):
        idx = make_index(make_index_entry(slug="awslabs__mcp", repo="awslabs/mcp"))
        full = {"awslabs__mcp": self._full_with_subs("awslabs__mcp", [
            {"name": "ec2", "subpath": "packages/ec2", "tools_count": 1,
             "tools": [{"name": "describe", "description": "", "input_keys": []}],
             "extraction_method": "ast_python"},
        ])}
        out = render_api._expand_sub_servers(idx, full)
        sub = next(s for s in out["servers"] if s["slug"] == "awslabs__mcp__ec2")
        assert sub.get("parent_slug") == "awslabs__mcp"
        assert sub.get("subpath") == "packages/ec2"

    def test_virtual_entry_inherits_composite_and_license(self):
        idx = make_index(make_index_entry(slug="awslabs__mcp", composite=94))
        full = {"awslabs__mcp": self._full_with_subs("awslabs__mcp", [
            {"name": "x", "subpath": "packages/x", "tools_count": 1,
             "tools": [{"name": "t", "description": "", "input_keys": []}],
             "extraction_method": "regex_typescript"},
        ])}
        out = render_api._expand_sub_servers(idx, full)
        sub = next(s for s in out["servers"] if s["slug"].endswith("__x"))
        assert sub["composite"] == 94
        assert sub["language"] == "Python"
        # subkind on the virtual entry is `integration` — only the parent is
        # the agent-product (the suite). Each sub IS an integration server.
        assert sub["subkind"] == "integration"

    def test_virtual_tool_count_is_sub_specific(self):
        idx = make_index(make_index_entry(slug="parent", composite=80))
        full = {"parent": self._full_with_subs("parent", [
            {"name": "small", "subpath": "p/small", "tools_count": 2,
             "tools": [{"name": "a", "description": "", "input_keys": []},
                       {"name": "b", "description": "", "input_keys": []}],
             "extraction_method": "ast_python"},
            {"name": "big", "subpath": "p/big", "tools_count": 50,
             "tools": [{"name": f"t{i}", "description": "", "input_keys": []} for i in range(50)],
             "extraction_method": "ast_python"},
        ])}
        out = render_api._expand_sub_servers(idx, full)
        small = next(s for s in out["servers"] if s["slug"].endswith("__small"))
        big = next(s for s in out["servers"] if s["slug"].endswith("__big"))
        assert small["tool_count"] == 2
        assert big["tool_count"] == 50

    def test_capabilities_inherit_when_sub_lacks_them(self):
        # If sub-server's tools don't carry capability metadata, inherit
        # from parent. Sub-specific capability reasoning is a future
        # enhancement; for now consistency with parent is the safe default.
        idx = make_index(make_index_entry(slug="parent", capabilities=["cloud", "devtools"]))
        full = {"parent": self._full_with_subs("parent", [
            {"name": "x", "subpath": "p/x", "tools_count": 1,
             "tools": [{"name": "t", "description": "", "input_keys": []}],
             "extraction_method": "ast_python"},
        ])}
        full["parent"]["capabilities"] = ["cloud", "devtools"]
        out = render_api._expand_sub_servers(idx, full)
        sub = next(s for s in out["servers"] if s["slug"].endswith("__x"))
        assert "cloud" in sub["capabilities"]


class TestRenderToolsIndex:
    """Bug #6 follow-up: a flat searchable index of every extracted tool
    across every server. Lets agents go from intent → specific tool → server
    in one fetch instead of N server-detail roundtrips.
    """

    def test_basic_shape(self):
        # Per-server JSONs include "tools" summary with names
        full_servers = {
            "x__a": {"repo": "x/a", "tools": {
                "tool_count": 2,
                "tool_names_preview": ["read_file", "write_file"],
                "extraction_method": "regex_typescript",
            }},
            "x__b": {"repo": "x/b", "tools": {
                "tool_count": 1,
                "tool_names_preview": ["browser_navigate"],
                "extraction_method": "regex_typescript",
            }},
        }
        idx = make_index(
            make_index_entry(slug="x__a", repo="x/a", composite=80),
            make_index_entry(slug="x__b", repo="x/b", composite=70),
        )
        result = render_api.render_tools_index(idx, full_servers)
        assert result["total_tools"] == 3
        # Each tool entry must include name + repo + slug + composite
        for entry in result["tools"]:
            for key in ("name", "repo", "slug", "composite"):
                assert key in entry

    def test_dedupes_identical_names_across_servers(self):
        # Multiple servers can expose `read_file`. We keep both rows so an
        # agent can compare quality, but ensure the schema supports it.
        full_servers = {
            "a__one": {"repo": "a/one", "tools": {"tool_count": 1, "tool_names_preview": ["read_file"], "extraction_method": "regex_typescript"}},
            "b__two": {"repo": "b/two", "tools": {"tool_count": 1, "tool_names_preview": ["read_file"], "extraction_method": "regex_typescript"}},
        }
        idx = make_index(
            make_index_entry(slug="a__one", repo="a/one", composite=90),
            make_index_entry(slug="b__two", repo="b/two", composite=70),
        )
        result = render_api.render_tools_index(idx, full_servers)
        # Both entries present
        names = [t["name"] for t in result["tools"]]
        assert names.count("read_file") == 2
        # Sorted by composite desc — agent reading top-K gets best provider first
        for_read_file = [t for t in result["tools"] if t["name"] == "read_file"]
        assert for_read_file[0]["composite"] >= for_read_file[1]["composite"]

    def test_servers_without_tools_skipped(self):
        full_servers = {
            "x__a": {"repo": "x/a", "tools": {"tool_count": 0, "tool_names_preview": [], "extraction_method": "none"}},
            "x__b": {"repo": "x/b", "tools": {"tool_count": 1, "tool_names_preview": ["foo"], "extraction_method": "regex_typescript"}},
        }
        idx = make_index(
            make_index_entry(slug="x__a", repo="x/a"),
            make_index_entry(slug="x__b", repo="x/b"),
        )
        result = render_api.render_tools_index(idx, full_servers)
        assert result["total_tools"] == 1
        assert result["tools"][0]["repo"] == "x/b"

    # G4 (Opus + Codex consensus): tools-index lossy. Currently flattens
    # only `tool_names_preview` (capped at 10 names). Drops descriptions
    # and input_keys that the extractor already produces. find_tool can't
    # rank by intent because there's no intent-bearing text.
    def test_includes_full_tool_records_with_descriptions(self):
        full_servers = {
            "x__a": {
                "repo": "x/a",
                "tools": {"tool_count": 1, "tool_names_preview": ["read_file"], "extraction_method": "ast_python"},
            }
        }
        # The full extraction is in `tools_extraction` on the per-server JSON
        # — render_tools_index reads it directly to recover descriptions.
        full_servers["x__a"]["tools_extraction"] = {
            "tools": [
                {"name": "read_file", "description": "Read a file from disk by path", "input_keys": ["path"]},
            ]
        }
        idx = make_index(make_index_entry(slug="x__a", repo="x/a", composite=80))
        result = render_api.render_tools_index(idx, full_servers)
        assert result["total_tools"] == 1
        entry = result["tools"][0]
        assert entry["name"] == "read_file"
        assert entry["description"] == "Read a file from disk by path"
        assert entry["input_keys"] == ["path"]

    def test_no_silent_truncation_for_aggregator_servers(self):
        # G4 (Opus): tool_names_preview was capped at [:10]. For awslabs/mcp
        # with 30+ tools the catalog silently dropped them, degrading
        # find_tool recall. tools-index now uses tools_extraction (full list),
        # not the preview cap.
        many_tools = [{"name": f"tool_{i}", "description": f"Tool {i}", "input_keys": []}
                      for i in range(30)]
        full_servers = {
            "x__suite": {
                "repo": "x/suite",
                "tools": {"tool_count": 30, "tool_names_preview": [f"tool_{i}" for i in range(10)],
                          "extraction_method": "regex_typescript"},
                "tools_extraction": {"tools": many_tools},
            }
        }
        idx = make_index(make_index_entry(slug="x__suite", repo="x/suite", composite=90))
        result = render_api.render_tools_index(idx, full_servers)
        assert result["total_tools"] == 30, (
            f"all 30 tools must be in tools-index, not capped at preview length"
        )

    # K2-3: sub-server tools surface in tools-index with virtual slug + parent_slug
    def test_sub_server_tools_appear_in_index(self):
        full_servers = {
            "awslabs__mcp": {
                "repo": "awslabs/mcp",
                "tools": {"tool_count": 0, "tool_names_preview": [],
                          "extraction_method": "none"},
                "tools_extraction": {"tools": []},
                "sub_servers": [
                    {"name": "dynamodb-mcp-server", "subpath": "packages/dynamodb-mcp-server",
                     "tools_count": 2, "extraction_method": "ast_python",
                     "tools": [
                         {"name": "get_item", "description": "Get item", "input_keys": ["table"]},
                         {"name": "put_item", "description": "Put item", "input_keys": ["table"]},
                     ]},
                ],
            }
        }
        idx = make_index(make_index_entry(slug="awslabs__mcp", repo="awslabs/mcp",
                                          kind="server", subkind="agent-product",
                                          composite=94))
        # tools-index is called on EXPANDED idx — simulate that
        idx_exp = render_api._expand_sub_servers(idx, full_servers)
        # Need full_servers entry for the virtual slug too — main() does this
        # by injecting tools_extraction equivalent. Our render_tools_index
        # reads full_servers[slug].tools_extraction. For virtual slugs,
        # the tools come from sub_servers — render_tools_index must look
        # them up by parent_slug + subpath. Test pins this contract.
        result = render_api.render_tools_index(idx_exp, full_servers)
        names = {t["name"] for t in result["tools"]}
        assert "get_item" in names
        assert "put_item" in names
        # Virtual entry slugs carry through
        get_item = next(t for t in result["tools"] if t["name"] == "get_item")
        assert get_item["slug"] == "awslabs__mcp__dynamodb-mcp-server"
        # Sub-server tool entries also carry parent_slug
        assert get_item.get("parent_slug") == "awslabs__mcp"


class TestAlternativesRankingQuality:
    """Bug #5 fix (v1.0.1): alternatives are now ranked by similarity ×
    sqrt(composite/100). A junk repo with perfect tag overlap loses to a
    strong partial-overlap repo, which is what 'fallback' semantics demand.
    """

    def test_high_quality_alternative_beats_low_quality_perfect_match(self):
        me = make_index_entry(slug="me", capabilities=["a", "b", "c"], composite=92)
        # 1.0 sim × sqrt(0.30) ≈ 0.548
        perfect = make_index_entry(slug="perfect", capabilities=["a", "b", "c"], composite=30)
        # 0.67 sim × sqrt(0.88) ≈ 0.628 — wins
        quality = make_index_entry(slug="quality", capabilities=["a", "b"], composite=88)
        result = render_api.render_alternatives(me, [me, perfect, quality])
        slugs = [a["slug"] for a in result["alternatives"]]
        assert slugs[0] == "quality", (
            f"Expected 'quality' (sim 0.67, comp 88) ahead of 'perfect' (sim 1.0, comp 30). Got: {slugs}"
        )

    def test_score_field_present_and_in_range(self):
        me = make_index_entry(slug="me", capabilities=["a"], composite=80)
        other = make_index_entry(slug="o", capabilities=["a"], composite=70)
        result = render_api.render_alternatives(me, [me, other])
        assert result["alternatives"]
        for alt in result["alternatives"]:
            assert "score" in alt
            assert 0.0 <= alt["score"] <= 1.0
            assert "similarity" in alt


class TestAlternativesBroadCapPenalty:
    """E3: cross-LLM testing flagged that alternatives sharing only a
    broad capability (`ai` or `devtools`) get high similarity scores
    despite being unrelated. Opus quote: 'overlap on a single mega-capability
    treats a shell agent (wcgw) and a docs server (context7) as alternatives
    to a browser automation server.'

    Penalty: when the only shared capability is one of the broad/common
    ones (ai, devtools), score is reduced. Specific shared capabilities
    (web, database, comms) keep full weight.
    """

    def test_only_broad_overlap_ranks_below_specific_overlap(self):
        # Target: capabilities=[web, ai]
        target = make_index_entry(slug="target", capabilities=["web", "ai"], composite=92)

        # Bad alternative: shares only `ai` (broad). Composite high but
        # capability fit is shallow — agent shouldn't see this as fallback.
        ai_only = make_index_entry(slug="ai_only", capabilities=["ai", "memory"], composite=92)

        # Good alternative: shares `web` (specific). Lower composite.
        web_only = make_index_entry(slug="web_only", capabilities=["web", "search"], composite=70)

        result = render_api.render_alternatives(target, [target, ai_only, web_only])
        slugs = [a["slug"] for a in result["alternatives"]]
        assert slugs[0] == "web_only", (
            f"Specific-capability overlap (web) should rank above broad-only (ai). "
            f"Got order: {slugs}"
        )

    def test_devtools_only_overlap_penalized(self):
        target = make_index_entry(slug="t", capabilities=["devtools", "comms"], composite=80)
        devtools_only = make_index_entry(slug="d", capabilities=["devtools", "ai"], composite=90)
        comms_overlap = make_index_entry(slug="c", capabilities=["comms"], composite=70)
        result = render_api.render_alternatives(target, [target, devtools_only, comms_overlap])
        # comms-overlap (specific) should rank above devtools-only (broad)
        slugs = [a["slug"] for a in result["alternatives"]]
        assert slugs[0] == "c"

    def test_specific_overlap_rewarded_normally(self):
        # Sanity: when no broad-only overlap is involved, ranking is unchanged.
        target = make_index_entry(slug="t", capabilities=["database"], composite=80)
        a1 = make_index_entry(slug="a1", capabilities=["database"], composite=90)
        a2 = make_index_entry(slug="a2", capabilities=["database"], composite=70)
        result = render_api.render_alternatives(target, [target, a1, a2])
        slugs = [a["slug"] for a in result["alternatives"]]
        assert slugs == ["a1", "a2"]
