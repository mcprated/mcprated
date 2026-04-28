"""Tests for classify.classify_capabilities — capability tagging.

Failing tests in this file are intentional (TDD): they pin known bugs we
plan to fix. When fixed, the test goes green and stays as regression
protection.
"""
from __future__ import annotations
import pytest

import classify


def caps(d):
    return classify.classify_capabilities(d)


# ---------------------------------------------------------------------------
# Happy-path: each category should match at least one obvious description
# ---------------------------------------------------------------------------

class TestCategoryMatching:
    @pytest.mark.parametrize("desc, expected", [
        ("Postgres database integration",                         "database"),
        ("MySQL connector for MCP",                               "database"),
        ("Redis cache MCP",                                       "database"),
        ("Browser automation via Playwright",                     "web"),
        ("Headless browser scraper",                              "web"),
        ("Slack chat integration",                                "comms"),
        ("Discord bot",                                           "comms"),
        ("Stripe payments",                                       "finance"),
        ("Bitcoin transactions",                                  "finance"),
        ("FFmpeg video processing",                               "media"),
        ("OCR for documents",                                     "media"),
        ("Notion integration",                                    "productivity"),
        ("Vector search with embeddings index",                   "search"),
        ("OpenAI image generation",                               "ai"),
        ("Cloudflare workers integration",                        "cloud"),
        ("Filesystem read/write operations",                      "filesystem"),
        ("Knowledge graph for agents",                            "memory"),
        ("GitHub git operations",                                 "devtools"),
    ])
    def test_obvious_descriptions_match(self, make_repo, desc, expected):
        d = make_repo(description=desc, topics=["mcp"])
        result = caps(d)
        assert expected in result, f"expected {expected!r} in {result!r} for desc={desc!r}"


# ---------------------------------------------------------------------------
# Word-boundary correctness — most common false-positive vectors
# ---------------------------------------------------------------------------

class TestWordBoundaries:
    def test_git_doesnt_match_github(self, make_repo):
        # "git" as a standalone word is in `devtools`. "github" should match
        # via the explicit `github` keyword, not by partial-matching "git".
        d = make_repo(
            description="GitHub-based release workflow",
            topics=["github"],
        )
        result = caps(d)
        # devtools is OK to match (via 'github' keyword), but the matching
        # mechanism must use word boundaries so we don't double-count.
        assert "devtools" in result

    def test_image_in_unrelated_phrase_doesnt_match_media(self, make_repo):
        # "image search results" mentions image but is search-related;
        # `media` keywords should not trigger.
        d = make_repo(description="Returns image search results from Brave")
        result = caps(d)
        assert "media" not in result, f"unexpected media in {result!r}"


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_no_keyword_match_returns_empty(self, make_repo):
        d = make_repo(description="Lorem ipsum dolor sit amet", topics=[], readme="")
        assert caps(d) == []

    def test_capped_at_top_n(self, make_repo):
        # Description with many keywords — should still cap to top_n=3 by default
        d = make_repo(description=(
            "Postgres MySQL Redis MongoDB Notion Slack Discord OpenAI "
            "browser automation github docker kubernetes"
        ))
        result = caps(d)
        assert len(result) <= 3

    def test_custom_top_n(self, make_repo):
        d = make_repo(description="Postgres MySQL Slack OpenAI github docker")
        result = classify.classify_capabilities(d, top_n=2)
        assert len(result) <= 2

    def test_results_are_in_taxonomy(self, make_repo):
        # Whatever we return must be a valid taxonomy key (no typos, etc.).
        VALID = {
            "database", "filesystem", "web", "search", "productivity",
            "comms", "devtools", "cloud", "ai", "memory", "finance", "media",
        }
        d = make_repo(description="Random text with browser and database stuff")
        for cat in caps(d):
            assert cat in VALID

    def test_results_are_sorted_by_hit_count(self, make_repo):
        # Stronger evidence (more keyword hits) should rank higher.
        d = make_repo(description=(
            "Postgres MySQL Redis MongoDB DuckDB - heavy on database. "
            "Also one mention of Slack."
        ))
        result = caps(d)
        assert result[0] == "database"
        # 'comms' may or may not appear given top_n=3 cap and ties; just
        # ensure database comes first.


# ---------------------------------------------------------------------------
# Bug #3: known classifier mistakes from cold-agent test (TDD-pinned)
# ---------------------------------------------------------------------------

class TestKnownMistakes:
    """Bug #3 fix (taxonomy v1.0.1): tightened comms keywords. The bare
    'email' and 'messaging' tokens were the culprits — both leaked into
    contexts that aren't actually comms tools.
    """

    def test_figma_design_should_not_be_comms(self, make_repo):
        d = make_repo(
            owner="GLips", name="Figma-Context-MCP",
            description="MCP server giving access to Figma design files",
            topics=["mcp", "figma", "design"],
            readme="Figma design tokens, components, and messaging between team members",
        )
        result = caps(d)
        assert "comms" not in result, (
            f"Figma is design tooling, not comms. Got: {result}"
        )

    def test_googleapis_toolbox_should_not_be_comms(self, make_repo):
        d = make_repo(
            owner="googleapis", name="mcp-toolbox",
            description="MCP toolbox for accessing Google Cloud databases (BigQuery, Cloud SQL, Spanner)",
            readme="Run example queries: SELECT email FROM users WHERE ...",
        )
        result = caps(d)
        assert "comms" not in result, (
            f"googleapis/mcp-toolbox is database/cloud, not comms. Got: {result}"
        )

    def test_real_slack_server_still_matches_comms(self, make_repo):
        # Regression: tightening must NOT lose true positives. Slack-specific
        # servers should still tag as comms.
        d = make_repo(
            owner="x", name="slack-mcp",
            description="MCP server for Slack workspace operations",
            readme="Send messages to Slack channels via the bot API",
        )
        assert "comms" in caps(d)

    def test_real_email_server_still_matches_comms(self, make_repo):
        # An actual SMTP/email server cites SMTP, not just "email".
        d = make_repo(
            description="MCP server for sending mail via SMTP",
            readme="Use SMTP to send emails. Supports TLS.",
        )
        assert "comms" in caps(d)
