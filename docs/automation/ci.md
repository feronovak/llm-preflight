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

From 2.22.0, a required check can block a pull request unless a fresh,
passing CI record matches its contract, routes and prompts. The
[record workflow](github-action.md#proof-of-preflight) attests each approved
paid smoke and uploads the record as the `llm-preflight-record` artifact. This
workflow downloads the records of that workflow's recent runs on `main`, and
only those, then runs the gate offline.

The install in the workflow below is the published package, `llm-preflight==2.21.2`. `llm-preflight==2.22.0` is not an available package or tag yet.

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
      - run: python -m pip install "llm-preflight==2.21.2"
      # Only runs on main count: a push to main, or a maintainer's dispatch
      # from main. A run on any other branch, or for a pull request, is
      # never downloaded, whatever its branch is called.
      - name: Download the records of recent runs on main
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          mkdir -p records
          for event in push workflow_dispatch; do
            gh run list --repo "$GITHUB_REPOSITORY" \
              --workflow llm-preflight-record.yml --branch main --event "$event" \
              --status completed --limit 20 --json databaseId --jq '.[].databaseId'
          done | while read -r run_id; do
            artifacts="$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$run_id/artifacts" \
              --jq '[.artifacts[] | select(.name == "llm-preflight-record" and (.expired | not))] | length')"
            if [ "$artifacts" != 0 ]; then
              gh run download "$run_id" --repo "$GITHUB_REPOSITORY" \
                --name llm-preflight-record --dir "records/$run_id"
            fi
          done
      # Optional, for signed records (public repositories, or GitHub Enterprise Cloud).
      # Only the record workflow, run from main, signs a record this accepts.
      - name: Verify each record's signature
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          for record in records/*/*.preflight.json; do
            [ -e "$record" ] || continue
            gh attestation verify "$record" --repo "$GITHUB_REPOSITORY" \
              --signer-workflow "$GITHUB_REPOSITORY/.github/workflows/llm-preflight-record.yml" \
              --source-ref refs/heads/main \
              --predicate-type https://in-toto.io/attestation/test-result/v0.1
          done
      - name: Gate
        # The record workflow runs one default --smoke repetition, so the gate
        # requires --smoke; GITHUB_REPOSITORY names the repository whose
        # records count.
        run: |
          mkdir -p records
          llm-preflight gate benchmark.json --smoke --records records
```

The gate step fails the check on exit 1 (blocked) and exit 3 (the gate cannot
decide); its output starts with the reason, then numbered next steps. The gate
fingerprints `benchmark.json` from the pull request's checkout, so a record
for the previous contract, routes or prompts blocks with `contract_changed`,
`routes_changed` or `prompt_changed`. It decides on the newest record that
matches, so records of other pull requests' contracts among the downloads
never count. It never compares the config or result file a record names,
because the pull request controls the checkout. It counts only records from
`GITHUB_REPOSITORY`, which Actions sets in every job; a record from another
repository blocks with `foreign_record`. Give the gate the same selection
flags as the run that wrote the record (`--prompt`, `--tests`, `--env`,
`--migration-check`, `--smoke`): the Action runs a default `--smoke`, so this
gate takes `--smoke`, and a workflow that runs
`llm-preflight benchmark.json --smoke --env staging` and attests its result
needs `--smoke --env staging` here, or the gate blocks with
`selection_changed`.

A pull request that changes the contract gets its record from `main`: a
maintainer reviews its diff, then starts the record workflow from `main` with
the pull request's head commit as the `commit` input (Actions → LLM
preflight record → Run workflow, or
`gh workflow run llm-preflight-record.yml --ref main -f commit=SHA`). That run
sends the provider credentials to whatever the pull request's configuration
names, so review its routes first: a changed `base_url` sends the key to
another host, and a changed `api_key_env` can send any variable of the job,
such as the token the signing step uses. `llm-preflight benchmark.json
--doctor` checks for free that every route resolves, but it cannot tell
whether a host is yours: the diff is the review. Records
from a pull request's own branch never count: anyone who can push a branch
could otherwise edit the record workflow in one commit, record, and restore
it in the next.

The gate is only as trustworthy as where it runs. Make this workflow a
required status check that the pull request cannot edit: require it with a
repository ruleset or a required workflow, or require code-owner review for
`.github/workflows/`. A record is only as trustworthy as the workflow that
produced it, so keep the record workflow behind an environment with required
reviewers; `--signer-workflow` and `--source-ref refs/heads/main` make the
signature step accept only that workflow, run from `main`. The gate does not
stop a maintainer who can edit these workflows or approve their own paid run.
Remove the signature step on a private repository without GitHub Enterprise
Cloud. The [proof-of-preflight guide](../guides/proof-of-preflight.md) lists
every reason code and what to do when the gate blocks.

## Release documentation checklist

For every release, update the package version, the README's current
what's-new section, `examples/github-actions/preflight.yml`, and the matching
version expectations in `tests/test_package.py` together. Then run the package
and documentation checks before tagging, so public installation instructions
and release examples cannot drift from the published artifact.
