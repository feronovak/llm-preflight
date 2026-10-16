# CI and JSON output

**Last reviewed:** 2026-10-14 · **As of:** v2.21.2

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
rate drop, a cost increase beyond its configured threshold, or different
output-contract evidence. Legacy artifacts without provenance are reported as
`unknown` comparability so their metric deltas remain visible. Costs are
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
or test fixture, not as a passing production gate. A GitHub workflow that
verifies the mock fixture should explicitly expect that exit code. The tracked
starter workflow pins the latest published package, 2.21.2; verify the
workflow against that package when updating the pin.

For a mock-evidence job, preserve the JSON artifact while accepting only the
expected inconclusive status:

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

In 2.18.0, billable runs with missing usage or unobserved retry
usage are inconclusive (exit 3), even when the output contract passes. Preserve
the null total and incomplete subtotal in CI consumers. Legacy artifacts
without `cost_coverage` cannot substantiate cost completeness or savings.
Unsupported output-schema constraints fail before requests (exit 2). Strict
pricing checks expire dated evidence independently of source descriptions.
The starter workflow remains pinned to the latest published package until the
new release is available.
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

## Proof-of-preflight gate

From 2.22.0, a pull request can be blocked unless a fresh, passing CI record
matches its contract and routes. The
[record workflow](github-action.md#proof-of-preflight) attests each approved
paid smoke and uploads the record as the `llm-preflight-record` artifact. This
workflow downloads the newest record, from the pull request's branch if a
maintainer ran the record workflow there and from `main` otherwise, then runs
the gate offline:

```yaml
name: LLM preflight gate
on:
  pull_request:
permissions:
  contents: read
  actions: read        # list runs and download their artifacts
  attestations: read   # the optional signature check
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: "3.13"
      - run: python -m pip install "llm-preflight==2.22.0"
      - name: Find the newest record run
        id: source
        env:
          GH_TOKEN: ${{ github.token }}
          HEAD_REF: ${{ github.head_ref }}
        run: |
          for branch in "$HEAD_REF" main; do
            run_id="$(gh run list --repo "$GITHUB_REPOSITORY" \
              --workflow llm-preflight-record.yml --branch "$branch" \
              --status completed --limit 1 --json databaseId \
              --jq '.[0].databaseId // empty')"
            if [ -n "$run_id" ]; then
              echo "run-id=$run_id" >> "$GITHUB_OUTPUT"
              break
            fi
          done
      - name: Download the record
        if: steps.source.outputs.run-id != ''
        continue-on-error: true  # a run without a record leaves the gate no_record
        uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4
        with:
          name: llm-preflight-record
          path: records
          run-id: ${{ steps.source.outputs.run-id }}
          github-token: ${{ github.token }}
      # Optional, for signed records (public repositories, or GitHub Enterprise Cloud).
      - name: Verify the record's signature
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          for record in records/*.preflight.json; do
            [ -e "$record" ] || continue
            gh attestation verify "$record" --repo "$GITHUB_REPOSITORY" \
              --predicate-type https://in-toto.io/attestation/test-result/v0.1
          done
      - name: Gate
        # The record workflow runs a default smoke, so no selection flags;
        # GITHUB_REPOSITORY names the repository whose records count.
        run: |
          mkdir -p records
          llm-preflight gate benchmark.json --records records
```

The gate step fails the check on exit 1 (blocked) and exit 3 (the gate cannot
decide); its output starts with the reason, then numbered next steps. The gate
fingerprints `benchmark.json` from the pull request's checkout, so a record
for the previous contract blocks with `contract_changed`. It counts only
records from `GITHUB_REPOSITORY`, which Actions sets in every job; a record
from another repository blocks with `foreign_record`. Give the gate the same
selection flags as the run that wrote the record (`--prompt`, `--tests`,
`--env`, `--migration-check`): the Action runs a default smoke, so this gate
takes none, and a workflow that runs `llm-preflight benchmark.json --smoke
--env staging` and attests its result needs `--env staging` here too,
or the gate blocks with `selection_changed`. Remove the signature
step on a private repository without GitHub Enterprise Cloud. The
[proof-of-preflight guide](../guides/proof-of-preflight.md) lists every
reason code and what to do when the gate blocks.

## Release documentation checklist

For every release, update the package version, the README's current
what's-new section, `examples/github-actions/preflight.yml`, and the matching
version expectations in `tests/test_package.py` together. Then run the package
and documentation checks before tagging, so public installation instructions
and release examples cannot drift from the published artifact.
