"""Tests for linter/smoke.py — local smoke harness for scoring changes.

The harness is a thin wrapper around the existing crawler + lint pipeline.
The only nontrivial logic worth unit-testing is _diff_snapshots: comparing
two snapshots and emitting a structured diff (NEW / REMOVED / CHANGED).
"""
from __future__ import annotations

import smoke


def _entry(slug, **overrides):
    base = {
        "slug": slug,
        "repo": slug.replace("__", "/"),
        "composite": 80,
        "axes": {"reliability": 80, "documentation": 80, "trust": 80, "community": 80},
        "kind": "server",
        "subkind": "integration",
        "capabilities": ["devtools"],
        "tool_count": 0,
        "hard_flags": [],
    }
    base.update(overrides)
    return base


class TestDiffSnapshots:
    def test_identical_returns_empty_diff(self):
        before = {"servers": {"x__a": _entry("x__a")}}
        after = {"servers": {"x__a": _entry("x__a")}}
        diff = smoke._diff_snapshots(before, after)
        assert diff["new"] == []
        assert diff["removed"] == []
        assert diff["changed"] == []

    def test_new_server_listed_under_new(self):
        before = {"servers": {}}
        after = {"servers": {"x__a": _entry("x__a")}}
        diff = smoke._diff_snapshots(before, after)
        assert diff["new"] == ["x__a"]
        assert diff["removed"] == []
        assert diff["changed"] == []

    def test_removed_server_listed_under_removed(self):
        before = {"servers": {"x__a": _entry("x__a")}}
        after = {"servers": {}}
        diff = smoke._diff_snapshots(before, after)
        assert diff["removed"] == ["x__a"]
        assert diff["new"] == []
        assert diff["changed"] == []

    def test_composite_change_recorded(self):
        before = {"servers": {"x__a": _entry("x__a", composite=80)}}
        after = {"servers": {"x__a": _entry("x__a", composite=92)}}
        diff = smoke._diff_snapshots(before, after)
        assert len(diff["changed"]) == 1
        c = diff["changed"][0]
        assert c["slug"] == "x__a"
        # changes is a list of (field, before, after) tuples
        fields = {f for f, _, _ in c["changes"]}
        assert "composite" in fields

    def test_capability_set_change_recorded(self):
        before = {"servers": {"x__a": _entry("x__a", capabilities=["web", "ai"])}}
        after = {"servers": {"x__a": _entry("x__a", capabilities=["web", "devtools"])}}
        diff = smoke._diff_snapshots(before, after)
        assert len(diff["changed"]) == 1
        fields = {f for f, _, _ in diff["changed"][0]["changes"]}
        assert "capabilities" in fields

    def test_axis_score_change_recorded(self):
        before = {"servers": {"x__a": _entry("x__a")}}
        after_entry = _entry("x__a")
        after_entry["axes"] = {**after_entry["axes"], "trust": 100}
        after = {"servers": {"x__a": after_entry}}
        diff = smoke._diff_snapshots(before, after)
        # Axis changes should surface as `axes.trust`
        fields = {f for f, _, _ in diff["changed"][0]["changes"]}
        assert any("trust" in f for f in fields)

    def test_kind_change_recorded(self):
        before = {"servers": {"x__a": _entry("x__a", kind="server")}}
        after = {"servers": {"x__a": _entry("x__a", kind="ambiguous", subkind="")}}
        diff = smoke._diff_snapshots(before, after)
        fields = {f for f, _, _ in diff["changed"][0]["changes"]}
        assert "kind" in fields

    def test_hard_flag_addition_recorded(self):
        before = {"servers": {"x__a": _entry("x__a", hard_flags=[])}}
        after = {"servers": {"x__a": _entry("x__a", hard_flags=["archived"])}}
        diff = smoke._diff_snapshots(before, after)
        fields = {f for f, _, _ in diff["changed"][0]["changes"]}
        assert "hard_flags" in fields

    def test_tool_count_change_recorded(self):
        before = {"servers": {"x__a": _entry("x__a", tool_count=0)}}
        after = {"servers": {"x__a": _entry("x__a", tool_count=15)}}
        diff = smoke._diff_snapshots(before, after)
        fields = {f for f, _, _ in diff["changed"][0]["changes"]}
        assert "tool_count" in fields

    def test_unchanged_fields_not_listed(self):
        # Only changed fields should appear in `changes`, not the whole entry
        before = {"servers": {"x__a": _entry("x__a", composite=80)}}
        after = {"servers": {"x__a": _entry("x__a", composite=82)}}
        diff = smoke._diff_snapshots(before, after)
        c = diff["changed"][0]
        fields = {f for f, _, _ in c["changes"]}
        # composite changed; nothing else did
        assert fields == {"composite"}


class TestRenderDiff:
    """Smoke output is stdout text. Ensure the formatter is deterministic
    and includes the key human-readable bits."""

    def test_no_changes_prints_concise_message(self):
        diff = {"new": [], "removed": [], "changed": []}
        text = smoke._render_diff(diff, before_ts="A", after_ts="B")
        assert "NO CHANGES" in text or "no changes" in text.lower()

    def test_new_section_only_when_present(self):
        diff = {"new": ["x__a"], "removed": [], "changed": []}
        text = smoke._render_diff(diff, before_ts="A", after_ts="B")
        assert "x__a" in text
        assert "NEW" in text

    def test_changed_renders_field_old_to_new(self):
        diff = {
            "new": [], "removed": [],
            "changed": [{"slug": "x__a", "repo": "x/a",
                         "changes": [("composite", 80, 92)]}],
        }
        text = smoke._render_diff(diff, before_ts="A", after_ts="B")
        assert "x/a" in text or "x__a" in text
        # Format should make old → new direction obvious
        assert "80" in text and "92" in text


class TestPruneOldSnapshots:
    def test_keeps_only_last_n(self, tmp_path):
        d = tmp_path
        # Create 15 timestamped files
        for i in range(15):
            (d / f"2026-04-29T{i:02d}.json").write_text("{}")
        smoke._prune_history(d, keep=10)
        remaining = sorted(d.glob("*.json"))
        assert len(remaining) == 10
        # Oldest got pruned, newest survived
        assert remaining[-1].name == "2026-04-29T14.json"
        assert remaining[0].name == "2026-04-29T05.json"

    def test_does_nothing_when_under_limit(self, tmp_path):
        for i in range(3):
            (tmp_path / f"f{i}.json").write_text("{}")
        smoke._prune_history(tmp_path, keep=10)
        assert len(list(tmp_path.glob("*.json"))) == 3
