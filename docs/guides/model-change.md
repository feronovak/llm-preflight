# Workflows

Review a model, prompt or route change against an existing application rule.
Start with a reviewed config from [project integration](../getting-started/project-integration.md).
Keep approved and candidate routes, request settings, fixtures and spend limits
explicit. Commands below marked as live can incur provider cost.

- **Known models:** start with the migration check below, then use a custom
  contract for your feature.
- **New provider releases:** use the catalogue lifecycle.
- **A stable, automated check:** use the CI workflow after the contract is
  proven locally.

## Decide whether a model change is safe

First check the declared validator and preview the actual application workload
without generation:

```bash
llm-preflight benchmark.json --contract-check
llm-preflight benchmark.json --doctor
llm-preflight benchmark.json --pricing-check
llm-preflight benchmark.json --dry-run
```

Resolve warnings, preserve accepted and rejected fixtures, and review the
retry-expanded request bound. **Live requests:** only after authorizing that
plan, run `llm-preflight benchmark.json`. A direct CLI run has no separate
approval prompt. Keep its JSON decision and compare it with the reviewed
baseline; a successful API call alone is insufficient.

For a preliminary API compatibility check, preview the optional built-in pack:

```bash
llm-preflight benchmark.json --migration-check --dry-run
```

After reviewing its separate plan, the live command is
`llm-preflight benchmark.json --migration-check`. It sends three built-in cases
once per model before configured retries: a capital-city answer, summary and
rewrite. These cases do not substitute for your application's rule.

Built-in `structured-output-check` and `exact-routing-check` provide additional
examples. Use [custom contract tests](output-contracts.md) for the specific
request and output your feature must preserve. Latency and cost reflect this
host, account, route and sample; small runs do not establish stable rankings.

If the result fails, distinguish API errors from rejected responses. Inspect
the failed case, retain the validator and fix the integration or request. If
it is inconclusive, resolve the blocking warnings and missing evidence before
proposing approval. Use [CI and JSON output](../automation/ci.md) for baseline
comparison commands and exits.

## Maintain approved models

For a recurring provider-model review, use the catalogue lifecycle—not a
runtime `discovery` config directly. It creates an ignored local workspace,
keeps temporary candidates separate from permanent approved models, and uses
the normal interactive benchmark screen for the paid run.

```bash
llm-preflight catalog init
llm-preflight catalog refresh benchmarks/watch.json
# Only if the catalogue says a model "Needs one probe":
llm-preflight catalog probe benchmarks/watch.json
llm-preflight catalog prepare benchmarks/watch.json \
  --against benchmarks/approved.json --output benchmarks/candidates.json
llm-preflight benchmarks/candidates.json --migration-check --dry-run
# Paid only after reviewing the interactive plan and confirming:
llm-preflight benchmarks/candidates.json --interactive \
  --approve-to benchmarks/approved.json
```

Refresh is metadata-only. A probe is one confirmed, minimal request for a text
candidate; it is optional and may be billable. `prepare` then offers only models
known to be compatible with the generic text benchmark.

To run your permanent baseline later, create its runnable test plan with
`catalog test WATCH --approved APPROVED --output CONFIG`, then run that config
interactively. To retire a permanent model, use `models remove PROVIDER:MODEL
--approved APPROVED`; it asks for confirmation and retains past evidence.

See [Model watch and approval](model-catalog.md) for the full first-run and
re-review process. `watch-new` is retained only for compatibility with older
scripts.

## Discovery and interactive selection

Use `discovery` in a config to resolve provider catalogs at run time. Every
source requires a positive `limit` as a cost-safety control.

```json
{
  "discovery": [
    {"provider": "openrouter", "sort": "newest", "output_modalities": "text", "limit": 5}
  ]
}
```

```bash
llm-preflight benchmark.auto.example.json --catalog
llm-preflight benchmark.auto.example.json --interactive
```

Interactive benchmark mode presents a run plan before confirmation. Model
selections can be numbers, a provider such as `openai`, or a provider family
such as `openrouter/qwen`. It is for a benchmark run; use `catalog probe` only
for the separate one-request compatibility check described in the catalogue
tutorial.

## Fast checks

```bash
# No generation: inspect the reduced run before deciding to spend.
llm-preflight benchmark.json --smoke --dry-run
# Paid: only after separately reviewing and authorizing that plan.
llm-preflight benchmark.json --smoke

# Configuration and pricing checks without generation.
llm-preflight benchmark.json --doctor
llm-preflight benchmark.json --pricing-check

# Local mock prompt without a config file; inconclusive exit 3 is expected.
llm-preflight --quick "Reply with ok." --models mock:local --no-save
```

Smoke mode still makes paid requests. It reduces normal request settings but
does not remove an explicitly selected `concurrency-health-check`; always
inspect the dry run first.

## Select, stop, and retain

Use `--tests` (or the compatibility alias `--profiles`) to select built-in and
custom tests together:

```bash
llm-preflight benchmark.json --tests exact-routing-check,source-to-quiz
```

Choose `--stop-on api-error`, `test-fail`, or `any-fail`; omit `--stop-on` to
run every selected model. `--fail-fast` remains an alias for
`--stop-on any-fail`. Use `--no-save` when CI only needs stdout and an exit
status. See [CI and JSON output](../automation/ci.md) for automation recipes.

## Compare and automate

```bash
llm-preflight --diff results/old.json results/new.json
llm-preflight benchmark.json --baseline results/old.json --ci
llm-preflight --replay results/run.json
llm-preflight benchmark.json --tests all --matrix
llm-preflight benchmark.auto.json --changed-since catalog.json --dry-run
```

With `--json`, `--baseline` emits one JSON result document with the comparison
under `baseline_diff`; it is safe to pipe into a JSON parser. `--replay` loads
the saved result's source configuration and the `.env.production` file beside
that configuration unless an explicit environment-file option overrides it.

`--changed-since` runs only discovered models absent from a previous catalog
snapshot. Set `max_requests` and `max_estimated_cost_usd` in a config to stop
surprise spend before requests are sent; a cost ceiling requires complete
pricing for every selected model.

See [configuration](../reference/configuration.md) for aliases and environment overlays.
