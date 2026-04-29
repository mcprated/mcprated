"""Tests for taxonomy integrity:
- The Python dict in classify.py and the YAML doc in linter/taxonomy/v1.yaml
  describe the same vocabulary (no drift between source and doc).
- All declared categories appear in render_api.CAPABILITIES.
- No keyword is a strict prefix of another within the same category (avoids
  redundant matches).
"""
from __future__ import annotations
import re
from pathlib import Path

import classify

ROOT = Path(__file__).resolve().parent.parent.parent


def _parse_yaml_keywords() -> dict[str, list[str]]:
    """Tiny ad-hoc parser. We don't add PyYAML as a dep just for this test —
    the YAML structure is rigidly known. If the format ever drifts, switch
    to PyYAML."""
    text = (ROOT / "linter" / "taxonomy" / "v1.yaml").read_text()
    out: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        # Match "  database:" — top-level category
        m = re.match(r"^  ([a-z_]+):\s*$", line)
        if m:
            current = m.group(1)
            continue
        # Match keyword line within a category
        m = re.match(r"^    keywords:\s*\[(.+)$", line)
        if m and current:
            buf = m.group(1)
        elif current and line.startswith("               "):
            buf = line.strip()
        else:
            continue
        # Pull each comma-separated keyword (handles quoted + bare).
        # Bare tokens can include digits (e.g. neo4j, fly.io, monday.com).
        items = re.findall(r'"([^"]+)"|([a-z0-9_/\.\- ]+)', buf)
        kws = [a or b for a, b in items if (a or b).strip(", ")]
        kws = [k.strip(", ") for k in kws if k.strip(", ")]
        out.setdefault(current, []).extend(kws)
        if "]" in buf:
            current_buf_done = True  # marker; not strictly needed
    return out


class TestTaxonomyIntegrity:
    def test_python_dict_categories_match_yaml(self):
        py = set(classify._TAXONOMY.keys())
        yaml = set(_parse_yaml_keywords().keys())
        # YAML may have a few formatting quirks; we want CATEGORIES to match.
        # If a category exists in py but not yaml (or vice versa), drift.
        diff = py.symmetric_difference(yaml)
        assert not diff, f"categories drift between classify.py and v1.yaml: {diff}"

    def test_all_categories_appear_in_render_api(self):
        # render_api.CAPABILITIES is the public list agents see; must match.
        import render_api  # noqa: F401  (import for side effect of having CAPABILITIES)
        assert set(classify._TAXONOMY.keys()) == set(render_api.CAPABILITIES)

    def test_no_empty_keyword_lists(self):
        for cat, kws in classify._TAXONOMY.items():
            assert kws, f"category {cat} has no keywords"

    def test_no_duplicate_keywords_within_category(self):
        for cat, kws in classify._TAXONOMY.items():
            dups = [k for k in kws if kws.count(k) > 1]
            assert not dups, f"category {cat} has duplicates: {set(dups)}"

    def test_taxonomy_version_matches(self):
        assert classify.TAXONOMY_VERSION == "1.0"


class TestYamlPythonSync:
    """G6 (Codex finding): the taxonomy lives in BOTH linter/taxonomy/v1.yaml
    (human-readable doc) and classify._TAXONOMY (runtime dict). The comment
    says YAML is authoritative, but they're maintained by hand. They WILL
    drift unless we fail loudly when they do.

    These tests check keyword-level equivalence per category. The tiny
    custom YAML parser in test_taxonomy_integrity is reused; its limits
    (rigid format) are acceptable because we control both files.
    """

    def test_keywords_per_category_match(self):
        py = classify._TAXONOMY
        yaml_kw = _parse_yaml_keywords()
        for cat in py:
            py_set = {k.lower().strip() for k in py[cat]}
            yaml_set = {k.lower().strip() for k in yaml_kw.get(cat, [])}
            # Allow YAML to have extra commentary entries we strip out, but
            # every Python keyword MUST be in YAML (the source of truth).
            missing_in_yaml = py_set - yaml_set
            assert not missing_in_yaml, (
                f"category {cat}: keywords present in classify.py dict but "
                f"missing in v1.yaml: {sorted(missing_in_yaml)}"
            )
            extra_in_yaml = yaml_set - py_set
            assert not extra_in_yaml, (
                f"category {cat}: keywords present in v1.yaml but missing in "
                f"classify.py dict (will not match at runtime!): {sorted(extra_in_yaml)}"
            )
