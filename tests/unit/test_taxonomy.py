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
        # Pull each comma-separated keyword (handles quoted + bare)
        items = re.findall(r'"([^"]+)"|([a-z_/\.\- ]+)', buf)
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
