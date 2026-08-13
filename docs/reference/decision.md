# Agent decision contract

Every completed benchmark result includes an additive `decision` object. It is
the machine-readable boundary for agents: consume it from the JSON artifact or
the MCP `run_preflight` result, rather than parsing terminal output.

## Versioning

`decision.schema_version` is independent of the enclosing result
`schema_version`. This document defines `decision.schema_version: 1`. Consumers
must reject an unknown decision schema version rather than guess its meaning.

## Shape

```json
{
  "schema_version": 1,
  "state": "pass",
  "reason_code": "benchmark_passed",
  "reason": "All requested models passed with complete, uninterrupted evidence.",
  "safe_next_command": "llm-preflight CONFIG --doctor --json",
  "blocking_warnings": []
}
```

`state` is exactly one of:

- `pass` — every requested model passed its configured contract and no degraded
  evidence condition was found.
- `fail` — one or more requested models failed a request or configured output
  contract. `fail` takes precedence over inconclusive evidence.
- `inconclusive` — no hard failure was observed, but evidence is degraded. Do
  not approve a change from an inconclusive result.

`reason_code` is `benchmark_passed`, `api_failure`, `contract_failure`, or
`degraded_evidence`, matching the state. `reason` is a concise explanation for
a person. API failures point to `--doctor --json`; a pure contract failure
points to `--dry-run --json` so the reviewed contract can be inspected without
new requests. When the source config path is known, `safe_next_command` quotes
that exact path; otherwise it uses the literal `CONFIG` placeholder.

## Blocking warnings

`blocking_warnings` is an ordered array of complete human-readable strings.
Agents must report every entry verbatim before suggesting a paid run or model
approval. It may be attached to `fail` as well as `inconclusive`, and covers:

- a selected billable route with unknown or stale pricing;
- `cost_confidence` other than `complete` for a run with billable routes; or
- a mock-only run, which is useful for local validation but cannot provide
  live-provider evidence.

Retries remain informational in each model summary. Their final-attempt latency
does not make the decision inconclusive.

An `inconclusive` state is not a failed benchmark. It means the result cannot
support a safe decision until its warnings are resolved or explicitly reviewed.
Replay decisions are wall-clock dependent: rerunning a saved configuration
re-evaluates live pricing freshness and new provider behavior at replay time.

## Exit status

The normal benchmark command exits `0` only for `decision.state: "pass"`, `1`
for `fail`, and `3` for `inconclusive`. Invalid input remains `2`; cancellation
remains `130`.

## Managed instruction block

The optional versioned `v1` instruction block emitted by `init` quotes this
contract. Its safe-next-command wording is: “Surface every
`blocking_warnings` entry verbatim, then run `llm-preflight CONFIG --doctor
--json` before paid work or approval.” The block adds guidance only; it never
grants paid-run approval.
