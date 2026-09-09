# CLI reference

**Last reviewed:** 2026-09-09 · **As of:** v2.14.0

Run `llm-preflight --help` for the installed version. The options below match this
release. `config` is a benchmark JSON path and is required unless `init` or `--init`,
`--quick`, `--diff`, or `--replay` is used.

`llm-preflight` is the primary command. From a source checkout, use
`python3 -m llm_preflight`. Use `--help` for the installed command surface and
`--version` to print the installed release.

| Option | Default | Purpose |
|---|---:|---|
| `--output-dir PATH` | `results` | Directory for saved result artifacts. |
| `--no-save` | off | Do not create result artifacts. |
| `--json` | off | Print the full result, plan, doctor report, or diff as JSON. |
| `--env NAME` | — | Apply a named configuration overlay. |
| `--smoke` | off | Set one repetition, no warmups, and concurrency one. It still makes paid requests; use `--dry-run` first. |
| `--migration-check` | off | Run the three-case `quick-migration-check` response-contract preflight once per selected model. |
| `--audit-source PATH` | — | Statically find literal model IDs in a repository, with no provider request or application-code execution. Pricing findings are advisory and identify confidence; they are not catalog or retirement verdicts. |
| `--change-plan [REF]` | `HEAD` | Inspect local Git changes against `REF`, including staged and untracked files, for literal model IDs and likely contract surfaces. It recommends no-spend commands; it never loads credentials, contacts a provider, or authorizes paid work. |
| `--contract-check` | off | Run configured accepted/rejected response fixtures, local image-fixture safety checks, and canonical tool-schema linting. It needs `validation_fixtures` or `tools`; it never loads credentials or contacts a provider. |
| `--doctor` | off | Validate configuration, keys, model resolution, redacted credential provenance, and selected-model pricing coverage; no generation. It does not by itself block a benchmark. |
| `--pricing-check` | off | Report selected direct models and OpenRouter routes with priced, undated, stale, or unknown pricing plus remediation; no generation. Its `pricing_coverage.ok` is false for stale or unknown prices; `pricing_coverage.enforcement_ok` is the exit/gate verdict and additionally fails undated pricing with `require_current_pricing: true`. |
| `pricing-refresh CONFIG [--write] [--offline] [--max-age-days DAYS] [--json]` | off | Propose or atomically write refreshed OpenRouter catalog prices and return full selected-model coverage; no generation. |
| `--baseline PATH` | — | Compare a completed run with a saved result. With `--json`, embeds `baseline_diff` in one JSON document. Results with different output-contract evidence are incompatible; legacy artifacts without provenance are labelled `unknown`. |
| `--ci` | off | Return exit code 1 if a requested baseline/diff regression fails. |
| `--matrix` | off | Print model-by-test quality matrix instead of the normal report. |
| `--quick TEXT` | — | Run one ad hoc prompt; requires `--models`. |
| `--init [PATH]` | `benchmark.json` | Create a no-key mock config without overwriting a file. |
| `init [PATH]` | `benchmark.json` | Create a mock config, or use `--template provider` with explicit provider, model, API-key environment-variable name, and optional config-relative `--env-file` reference. Add `--interactive` to collect the config path, provider, model, key-variable name, and optional env reference without prompting for a secret. `--agent-instructions PATH` opt-in writes only the marker-delimited managed block in that file. `--check` requires that flag and exits nonzero when the block is missing or drifted; it writes nothing. |
| `--models LIST` | — | Comma-separated `provider:model` list for `--quick`. An unprefixed ID is accepted only for recognizable OpenAI IDs. |
| `--diff BASELINE CURRENT` | — | Compare two saved JSON result files; no benchmark run. |
| `--replay PATH` | — | Re-run the saved source configuration in a result artifact. |
| `--changed-since PATH` | — | With discovery, run models absent from a prior catalog JSON. |
| `--catalog` | off | Discover and print selected models; no generation. |
| `--tests LIST` | — | Comma-separated built-in/custom test selector; `agent-smoke` is the recommended five-check suite. |
| `--profiles LIST` | — | Compatibility alias for `--tests`. |
| `--dry-run` | off | Safe preview: print resolved work, cost estimate, and `smoke_eligibility`; no generation. A model is eligible only with compatible catalogue type, adapter evidence, current pricing, and declared request/cost limits. |
| `--approval-receipt PATH` | — | With `--dry-run`, write an expiring private local receipt bound to that exact plan. Requires a review note and timezone-qualified expiry; never authorizes paid work. |
| `--verify-approval-receipt PATH` | — | With `--dry-run`, verify a receipt’s plan hash and expiry. A valid receipt is recorded evidence, not authorization. |
| `--no-env-file` | off | Do not load an env file. |
| `--env-file PATH` | — | Load this selected env file instead of a config reference or adjacent default. |
| `--stop-on MODE` | — | Stop after `api-error`, `test-fail`, or `any-fail`. |
| `--fail-fast` | off | Compatibility alias for `--stop-on any-fail`. |
| `--prompt NAME` | — | Run one named custom prompt from the config. |
| `--interactive` | off | Select models, tests, repetitions, and stop mode in the terminal. |
| `--approve-to PATH` | — | After an interactive saved run, offer passing models for explicit approval into this file. |

## Compatible combinations

- `--json` works with benchmark results, `--dry-run`, `--doctor`, `--contract-check`, `--diff`,
  `--baseline`, and `--catalog`. With `--baseline`, the comparison is embedded
  as `baseline_diff` in the single JSON result document.
- `--ci` gates `--diff` and `--baseline`; ordinary benchmark failures already
  exit with status 1.
- `--smoke`, `--env`, `--tests`, `--dry-run`, `--json`, `--no-save`, and
  `--stop-on` can be combined with a normal config run.

## Incompatible combinations and requirements

- `--quick` requires `--models` and does not use a config file.
- `--init` cannot be combined with `config`.
- `init` is the preferred first-run command. `--init` remains a compatibility alias.
- `--diff` runs alone; it compares its two positional JSON files.
- `--profiles` and `--tests` cannot be combined.
- `--migration-check` cannot be combined with `--profiles`, `--tests`,
  `--prompt`, or `--interactive`.
- `--contract-check` cannot be combined with `--profiles`, `--tests`, or
  `--migration-check`; it may use `--prompt` to check one named custom prompt.
- `--change-plan` requires a configuration rather than `--quick` or `--replay`.
- `--approval-receipt` and `--verify-approval-receipt` each require `--dry-run`
  and cannot be combined. Writing also requires `--approval-note` and
  `--approval-expires-at`.
- `--profiles`/`--tests` cannot be combined with `--prompt`.
- `--interactive` cannot be combined with `--catalog`, `--profiles`,
  `--tests`, or `--prompt`.
- `--no-env-file` and `--env-file` are mutually exclusive.
- `--approve-to` requires `--interactive` and cannot be combined with `--no-save`.

Omit `--stop-on` to run every selected model. The interactive menu calls that
choice `never`; it is not a command-line value.

## Exit codes and agent decisions

For a completed benchmark, exit code `0` means `decision.state` is `pass`;
`1` means `fail`; and `3` means `inconclusive`. Read the result's
`blocking_warnings` verbatim before proposing paid work or approval. Exit code
`2` remains invalid input or operational setup failure, and `130` remains a
cancelled operation. The decision is present in JSON artifacts and MCP
`run_preflight` results; see [Agent decision contract](decision.md).

## Built-in test packs

Use the names below in `--tests`; they are intentionally named for the decision
they support, not as broad claims about model intelligence.

| Test | Validates |
|---|---|
| `quick-migration-check` | API compatibility, basic response contract, TTFT, and latency. |
| `exact-routing-check` | Exact labels required by a downstream queue or action. |
| `structured-output-check` | JSON shape, required fields, and extracted values. |
| `numeric-instruction-check` | Numeric task correctness and concise instruction following. |
| `concurrency-health-check` | Basic reliability and latency at increasing concurrency. |
| `strict-json-extraction` | Raw JSON extraction with required fields and primitive types. |
| `support-classification` | Short, controlled-label customer support routing. |
| `code-patch-summary` | Concise, structured summaries of a small code change. |
| `source-grounded-quiz` | A small quiz derived only from supplied source material. |
| `refusal-boundary-check` | Privacy-sensitive requests receive a concise, safe boundary. |

`agent-smoke` combines the five agent-focused packs: `strict-json-extraction`,
`support-classification`, `code-patch-summary`, `source-grounded-quiz`, and
`refusal-boundary-check`. `chat-fast`, `classification`,
`structured-extraction`, `reasoning`, and `load` remain accepted as
compatibility aliases for existing configurations.

## Model lifecycle commands

Use the catalogue lifecycle below for all new work. It keeps discovery, the
temporary candidate plan, benchmark execution, and permanent approval separate.

| Command | Purpose |
|---|---|
| `catalog init [DIRECTORY] [--providers LIST] [--replace]` | Create an ignored local workspace with `watch.json`, `approved.json`, `.env.production`, and `results/`. Without `--providers`, it asks once and Enter means all supported providers. For an existing workspace, it asks before rewriting only `watch.json`; `--replace` is the scripted equivalent and preserves approvals, keys, and results. |
| `catalog refresh WATCH_CONFIG` | Fetch provider metadata, classify catalogue entries, update the local snapshot, and report per-model `smoke_eligibility`. It makes no generation requests. Optional legacy watch flags such as `--json`, `--snapshot`, and `--env-file` remain available. |
| `catalog prepare WATCH_CONFIG --against APPROVED --output CANDIDATES` | Group unapproved `text-ready` candidates by provider, require an explicit model selection, then write a temporary benchmark plan containing only smoke-eligible rows. `text-candidate` models first use `catalog probe`; non-text, unpriced, unbounded, or unproven rows remain visible in refresh eligibility output. Use `--replace` only when deliberately rebuilding that plan. |
| `catalog probe WATCH_CONFIG [--models LIST] [--no-env-file | --env-file PATH]` | Review `text-candidate` models, then make one explicitly confirmed, provider-native minimal request per selection. It uses the same explicit environment-file controls as benchmark runs. Results are saved locally in `.llm-preflight/capabilities.json`; response text and keys are never stored. |
| `catalog test WATCH_CONFIG --approved APPROVED --output CONFIG` | Write a runnable benchmark plan for permanent approved models, using the test settings in the watch config. |
| `CANDIDATES --interactive --approve-to APPROVED` | Run the single interactive benchmark flow, then offer passing models for approval. |
| `models approve PROVIDER:MODEL --from RESULT --approved APPROVED` | Explicitly approve one passing model from a saved result, optionally with `--note TEXT`. |
| `models remove PROVIDER:MODEL --approved APPROVED` | Confirm and remove a permanent model while recording a removal timestamp and optional `--note TEXT`. |

Example:

```bash
llm-preflight catalog init
llm-preflight catalog refresh benchmarks/watch.json
# Run only when a selected text model is labelled "Needs one probe".
llm-preflight catalog probe benchmarks/watch.json
llm-preflight catalog prepare benchmarks/watch.json \
  --against benchmarks/approved.json \
  --output benchmarks/candidates.json
llm-preflight benchmarks/candidates.json --interactive \
  --approve-to benchmarks/approved.json
```

`watch-new` and `approve-model` are compatibility aliases for existing scripts.
They expose legacy options and are not the recommended workflow. See
[Model watch and approval](../guides/model-catalog.md) for the complete tutorial.
