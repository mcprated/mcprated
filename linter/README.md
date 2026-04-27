# Linter

Python lint engine for MCPRated. Stdlib-only (no pip deps for V1).

## Quick run

```bash
export GITHUB_TOKEN=ghp_...
python linter/crawler.py --cache .cache --seed tests/regression/seed.txt
python linter/lint.py --cache .cache --out build
```

Output:
- `build/index.json` — list of all servers with composite + per-axis scores
- `build/servers/<owner>__<repo>.json` — full lint detail per server

## Files

| File | Role |
|---|---|
| `crawler.py` | Discover MCP repos + fetch metadata to local cache |
| `lint.py` | Apply 20 signals across 4 axes, produce score JSON |
| `rules/v1.0/*.yaml` | Open ruleset (declarative signal definitions) |

## Running on a single repo (debug)

```python
from linter.lint import lint
import json
data = json.load(open(".cache/owner__repo.json"))
print(json.dumps(lint(data), indent=2))
```

## Adding a new signal

1. Implement `s_my_new_signal(d)` in `lint.py` returning `(bool, str)`
2. Add to its axis list in `AXES`
3. Document in `rules/v1.0/<axis>.yaml`
4. Add regression test fixture
5. Bump `RULE_SET_VERSION` minor (1.0.0 → 1.1.0)
6. Update [CHANGELOG.md](../CHANGELOG.md)

See [methodology.md](../methodology.md) for governance and versioning policy.
