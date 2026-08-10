# Product map

**Last reviewed:** 2026-08-10 · **As of:** v2.4.3

What this tool does today. Present tense only — what is open belongs in the
roadmap, what shipped belongs in [`CHANGELOG.md`](../CHANGELOG.md).

Every row was read against the source at the version above, not inferred from
module names.

| Feature | State | Verified against |
|---|---|---|
| Cross-provider preflight run against a set of models before a switch | live | `runner.py`, `client.py` |
| CLI, as `llm-preflight` and `python -m llm_preflight` | live | `cli.py` (52 flags), `__main__.py` |
| Local stdio MCP server, `llm-preflight-mcp` — standard/2026 handshakes, safe live-run gate | live | `mcp.py` |
| `--doctor` — validate config, keys and model resolution without a run | live | `cli.py` |
| `--audit-source` — audit literal model IDs in a repository, no provider requests | live | `source_audit.py`, `cli.py` |
| `--baseline` / `--ci` — compare against a previous result, fail when thresholds regress | live | `cli.py` |
| `--changed-since` — run only models absent from a catalog snapshot | live | `catalog.py`, `catalog_watch.py` |
| `--interactive` with `--approve-to` — review a saved run, promote passing models | live | `cli.py` |
| Capability ledger — what each model was observed to support | live | `capability_ledger.py` |
| Pricing and cost reporting per run | live | `pricing.py`, `metrics.py` |
| Named profiles and presets for repeatable runs | live | `profiles.py`, `presets.py` |
| Secret redaction in output | live | `redaction.py`, `security.py` |
| `--json` output contract, consumed by CI and the MCP server | live | `cli.py`, `docs/reference/results.md` |

Nothing listed here is gated, partial or deprecated. Work proposed but not
built lives in the roadmap, which is deliberately not published — see the
contract in [`AGENTS.md`](../AGENTS.md).
