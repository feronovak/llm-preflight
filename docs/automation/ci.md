# CI and JSON output

## JSON output and exit status

`--json` writes a machine-readable result to stdout. Result saving notices go to
stderr, so redirecting stdout is safe. A benchmark exits 0 only for a `pass`
decision, 1 for `fail`, and 3 for `inconclusive` evidence. Cancellation exits
130. Treat the result's `blocking_warnings` as the authoritative explanation;
do not parse terminal output.

```bash
llm-preflight benchmark.json --json --no-save > current.json
```

Use `--dry-run --json` to inspect the exact paid-work plan in CI without making
requests. `--doctor --json`, `--pricing-check`, and `--catalog` are also safe
preflight steps.

Keep catalogue discovery separate from the benchmark gate. `catalog refresh`
fetches provider metadata and can be scheduled as an informational job, but
`catalog probe` deliberately sends a billable request and is best reviewed by a
person before it changes local compatibility evidence. CI should benchmark only
reviewed models in a known configuration or approved-test plan.

## Baseline gate

Keep a reviewed baseline result, write the current run to a file, then compare
them in a separate command:

```bash
llm-preflight benchmark.json --json --no-save > current.json
llm-preflight --diff baseline.json current.json --json --ci > comparison.json
```

The second command exits 1 when configured baseline thresholds regress and
otherwise exits 0. This two-command form writes a standalone comparison
artifact.

`--baseline baseline.json --ci` also gates a live run. With `--json`, it emits
exactly one JSON document and embeds the comparison as `baseline_diff`; with
human output, it prints the report followed by a readable diff. Prefer the
two-command form when a later CI step needs a standalone comparison artifact.

The CI comparison fails for a latency increase, a request-success or validation
rate drop, or a cost increase beyond its configured threshold. Costs are
compared only when both result files contain a known estimate; retain
`max_estimated_cost_usd` as the separate hard spend ceiling before a run.

Default comparison thresholds are latency p95 **+25%**, request success
**−5 percentage points**, validation rate **−5 percentage points**, and cost
**+25%**. A zero baseline uses the corresponding absolute increase threshold
for latency or cost because a percentage change is undefined.

When any custom threshold is configured, unspecified gates keep their defaults.
A baseline model missing from the current run is a failure, as is missing
validation evidence; request success alone does not substitute for a validated
output.

For the complete stable result structure, see [Result JSON schema](../reference/results.md).

## Safe CI starter

```bash
llm-preflight benchmark.json --doctor --json
llm-preflight benchmark.json --pricing-check
llm-preflight benchmark.json --smoke --dry-run --json
llm-preflight benchmark.json --smoke --json --no-save > current.json
```

A mock-only configuration intentionally exits 3: it proves local configuration
and report handling, not a live-provider decision. Use it for a no-key example
or test fixture, not as a passing production gate. A 2.7.0 GitHub workflow
should explicitly expect that exit code when its purpose is to verify the mock
fixture; the currently pinned released starter remains on 2.6.0 until 2.7.0 is
published.

For that 2.7.0 mock-evidence job, preserve the JSON artifact while accepting
only the expected inconclusive status:

```yaml
- name: Run the no-key mock evidence job
  run: |
    set +e
    llm-preflight examples/starter/mock-benchmark.json --smoke --json --no-save > results/current.json
    status=$?
    set -e
    test "$status" -eq 3
```

Set `max_requests` and `max_estimated_cost_usd` in the config to prevent
unexpected spend. Unknown pricing prevents cost-ceiling enforcement, so treat a
failed `--pricing-check` as a failed preflight.

Refresh OpenRouter catalog prices locally, review the printed field-level diff,
then write only when it is expected. The catalog lookup is public and does not
load `.env.production`; `--offline` verifies the local price ledger without a
network call.

```bash
llm-preflight pricing-refresh benchmark.json
llm-preflight pricing-refresh benchmark.json --write
llm-preflight pricing-refresh benchmark.json --offline --json
```

For coding-agent integration, use the dedicated [MCP server guide](mcp.md).
It documents the bounded local tool set, workspace rules, and explicit paid-run
confirmation separately from the CI workflow.

## GitHub Actions starter

Copy [the fork-safe mock workflow](../../examples/github-actions/preflight.yml) to
`.github/workflows/llm-preflight.yml`, and also copy
`examples/starter/mock-benchmark.json` into the same relative path in your
repository (or update the four workflow commands to your chosen mock config).
It uses no secrets, makes no paid request, and uploads JSON evidence even when
a check fails. It is safe for fork pull requests because it uses
`pull_request`, has read-only permissions, and does not use
`pull_request_target`.

The example pins the released CLI version and every action by commit SHA. Update
the CLI pin deliberately with each release. Add a live-provider job only in a
trusted branch workflow, with explicit repository-secret mapping, a reviewed
configuration, `max_requests`, and `max_estimated_cost_usd`; never run that job
against fork-controlled code. The example cancels superseded runs for the same
pull request. Do not copy that concurrency setting into a paid job unless the
provider requests are independently idempotent and cancellation-safe.
