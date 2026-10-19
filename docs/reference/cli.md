# CLI reference

**Last reviewed:** 2026-10-19 · **As of:** v2.22.2 (unreleased)

The main branch prepares **2.22.2**; the latest published package is **2.22.1**.
The new terminal/Markdown summary labels mocks, excludes them from provider
rankings, withholds cost/value recommendations when evidence warnings block
a conclusion, and calls monetary figures estimates. A complete passing
candidate can still be compared when another candidate fails its tests.
Machine decision schemas and benchmark exit codes are unchanged.

Run `llm-preflight --help` for the installed version. The options below match this
release. A normal benchmark takes `config`, a benchmark JSON path. Standalone
commands such as `init`, `catalog`, `models`, `report`, `attest`, `verify` and
`gate`, plus `--audit-source`, `--quick`, `--diff` and `--replay`, have their own
inputs; see their `--help`.

`llm-preflight` is the primary command. From a source checkout, use
`python3 -m llm_preflight`. Use `--help` for the installed command surface and
`--version` to print the installed release.

Render a saved result without running a benchmark:

```bash
llm-preflight report results/run.json --output report.html
llm-preflight report results/run.json --format markdown
llm-preflight report results/run.json --format svg --record results/run.preflight.json
```

The HTML is self-contained and opens offline. Every report format accepts only
schema-version-1 results and omits prompt/response content, local paths, and
identifying run metadata; the SVG card alone names the configuration, so a
shared card says which check it shows.

Unsupported output-schema keywords stop validation
before requests. Missing usage or unobserved retry usage keeps billable cost
incomplete and the decision inconclusive. Reports and comparisons flag legacy
artifacts without coverage; they do not convert missing cost into zero or
claim savings. Strict pricing freshness checks every source description.

| Option | Default | Purpose |
|---|---:|---|
| `report RESULT [--format html\|markdown\|svg] [--record RECORD] [--output PATH]` | HTML to stdout | Render saved schema-version-1 evidence offline; this command runs no benchmark. `svg` is the [preflight card](../guides/reports.md#preflight-card); `--record` adds the record's valid-until date and repository, and refuses a record that fails verification or attests another result. |
| `attest RESULT [--config PATH] [--output PATH] [--force] [--json]` | `RESULT` with `.preflight.json` | Write an in-toto record that this result's check ran, with its decision copied, never upgraded. It refuses a result without schema-version-1 provenance and never replaces a record without `--force`. `--config` defaults to the result's recorded `source_config_path`. The record carries the GitHub Actions run identity the result recorded when it ran, only when `attest` runs in that same run; otherwise its origin is `local` and `attest` prints why (`origin_reason` in `--json`). No provider request. |
| `verify RECORD [--max-age-days DAYS] [--json]` | 30 days | Report a record's integrity and freshness separately, with this verifier's retirement-snapshot date. Exit 0 intact and fresh, 1 integrity broken, 3 intact but stale or superseded. Signatures are not checked here; use `gh attestation verify`. |
| `gate [CONFIG] --records PATH... [--repository OWNER/NAME] [--env NAME] [--smoke] [--prompt NAME \| --tests LIST \| --migration-check] [--max-age-days DAYS] [--json]` | `benchmark.json`, `GITHUB_REPOSITORY`, a default run, 30 days | Decide offline whether a fresh, passing GitHub Actions record from this repository ran the same selection flags, as many times per prompt as the config asks, and matches the current contract, routes and prompts under them. Exit 0 pass, 1 blocked, 3 cannot decide, including when no repository is known or `--repository` contradicts `GITHUB_REPOSITORY`. It never fetches artifacts, loads credentials, reads the files a record names or contacts a provider. |
| `--output-dir PATH` | `results` | Directory for saved result artifacts. |
| `--no-save` | off | Do not create result artifacts. |
| `--json` | off | Print the full result, plan, doctor report, or diff as JSON. |
| `--env NAME` | — | Apply a named configuration overlay. |
| `--smoke` | off | Set one repetition, no warmups, and concurrency one. It still makes paid requests; use `--dry-run` first. |
| `--migration-check` | off | Run the three-case `quick-migration-check` response-contract preflight once per selected model. |
| `--audit-source PATH` | — | Statically find literal model IDs in a repository, with no provider request or application-code execution. Pricing findings are advisory. Each ID also gets a retirement verdict from the bundled snapshot of official deprecation pages, with date, provider-stated replacement and a ready `--quick --dry-run` command; `unknown` is not a verdict. In a Git work tree it reads tracked and unignored files only; elsewhere, or when the work tree ignores `PATH`, every file under `PATH`. Git runs with repository-configured commands disabled. The text output starts with the decision and the exit code, then groups findings by model ID, retired first, capped at ten models and three locations each. An audit that reads no file is `inconclusive` and says why. Exit 0 unless `--ci`. |
| `--all` | off | With `--audit-source`, print every model and location, including references with unknown pricing and no retirement finding. `--json` is never capped. |
| `--change-plan [REF]` | `HEAD` | Inspect local Git changes against `REF`, including staged and untracked files, for literal model IDs and likely contract surfaces. It recommends no-spend commands; it never loads credentials, contacts a provider, or authorizes paid work. |
| `--contract-check` | off | Run configured accepted/rejected response fixtures, local image-fixture safety checks, and canonical tool-schema linting. It needs `validation_fixtures` (top level or inside a custom prompt) or `tools`; it never loads credentials or contacts a provider. |
| `--doctor` | off | Validate configuration, keys, model resolution, redacted credential provenance, and selected-model pricing coverage; no generation. It does not by itself block a benchmark. Reports each approved model's retirement status: a retired model is a failed check (exit 1 even without `--ci`); retiring or stale is a warning. |
| `--pricing-check` | off | Report selected direct models and OpenRouter routes with priced, undated, stale, or unknown pricing plus remediation; no generation. Its `pricing_coverage.ok` is false for stale or unknown prices; `pricing_coverage.enforcement_ok` is the exit/gate verdict and additionally fails undated pricing with `require_current_pricing: true`. |
| `pricing-refresh CONFIG [--write] [--offline] [--max-age-days DAYS] [--json]` | off | Propose or atomically write refreshed OpenRouter catalog prices and return full selected-model coverage; no generation. |
| `--baseline PATH` | — | Compare a completed run with a saved result. With `--json`, embeds `baseline_diff` in one JSON document. Results with different output-contract evidence are incompatible; legacy artifacts without provenance are labelled `unknown`. |
| `--ci` | off | Return exit code 1 if a requested baseline/diff regression fails. With `--audit-source`, `--doctor` or `--dry-run`: 1 for a retired model, 3 retiring or stale; `--audit-source` also exits 3 when it read no file. |
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
| `--dry-run` | off | Safe preview: print resolved work, cost estimate, and `smoke_eligibility`; no generation. A model is eligible only with compatible catalogue type, adapter evidence, current pricing, and declared request/cost limits. Non-eligible models are listed with a reason and next step; eligibility gates `catalog prepare`, does not block a reviewed bounded run of text models, and a live run refuses the models it lists as refused. Lists retirement verdicts and next commands after eligibility. |
| `--approval-receipt PATH` | — | With `--dry-run`, write an expiring private local receipt bound to that exact plan. Requires a review note and timezone-qualified expiry; never authorizes paid work. |
| `--verify-approval-receipt PATH` | — | With `--dry-run`, verify a receipt’s plan hash and expiry. A valid receipt is recorded evidence, not authorization. |
| `--no-env-file` | off | Do not load an env file. |
| `--env-file PATH` | — | Load this selected env file instead of a config reference or adjacent default. |
| `--stop-on MODE` | — | Stop after `api-error`, `test-fail`, or `any-fail`. |
| `--fail-fast` | off | Compatibility alias for `--stop-on any-fail`. |
| `--prompt NAME` | — | Run one named custom prompt from the config. |
| `--interactive` | off | Guided selection and shared plan/fixture preview. Choose preview (default), save config, export plan, edit, or run; execution requires separate confirmation. With `--dry-run`, skip execution/acceptance prompts. |
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

With no saved stop rule, omit `--stop-on` to run every selected model. The
interactive menu calls that choice `never` and removes any saved stop rule;
it is not a command-line value.

The interactive flow accepts `q` to cancel and `back` to
revisit a selection; invalid choices can be corrected in place. With `--json`,
menus, prompts and progress go to stderr and stdout contains the final JSON.
For configured models, preview and mock execution do not load environment files;
provider discovery may need credentials before selection. Exports never replace
files, remove runtime fields and redact credentials/headers. Save a selected
config beside its source to preserve relative file references. See
[interactive runs](../guides/interactive-runs.md) for the action menu.

## Exit codes and agent decisions

For a completed benchmark, exit code `0` means `decision.state` is `pass`;
`1` means `fail`; and `3` means `inconclusive`. Read the result's
`blocking_warnings` verbatim before proposing paid work or approval. Exit code
`2` remains invalid input or operational setup failure, and `130` remains a
cancelled operation. The decision is present in JSON artifacts and MCP
`run_preflight` results; see [Agent decision contract](decision.md).

## Proof of preflight

A required gate check blocks a pull request that changes an LLM contract
until a fresh, passing check of that contract ran in this repository's CI. CI
attests the saved result of a bounded run and uploads the record as an
artifact; the gate checks the downloaded records against the current tree:

```bash
llm-preflight attest results/run.json
llm-preflight verify results/run.preflight.json
llm-preflight gate benchmark.json --repository acme/app --records records/
```

The gate passes only on the newest matching record that is `PASSED`,
consistent, fresh and not superseded, and that carries the identity of the
GitHub Actions run that made its result. It rejects a record tracked by Git
and never passes a local one. A record matches when its contract, routes,
prompts and the request options sent with each prompt equal the current
tree's; a changed prompt or request option blocks with `prompt_changed`. Its
text output gives the reason first, then numbered next steps, then the exit
line; `--json` carries the same `why` and `next` with a `reason_code` and a
verdict per record. Put `CONFIG` before `--records`, which takes every
following path. Only records from the expected repository count: in GitHub
Actions it is `GITHUB_REPOSITORY` on `GITHUB_SERVER_URL`; elsewhere pass
`--repository OWNER/NAME`, or the gate cannot decide (exit 3,
`repository_unknown`), because another repository's record can carry the
same fingerprints; it cannot decide either when `--repository` and
`GITHUB_REPOSITORY` disagree. Give the gate the selection flags the CI run
uses (`--env`, `--smoke`, `--prompt`, `--tests` or `--profiles`,
`--migration-check`): the record must have run exactly that selection, as
many times per prompt as the config asks, so a narrower run, a `--smoke` run
included, cannot stand in for the one the gate requires. `--env-file` only loads credentials and is not a selection. `verify` prints a `Route:` line per checked route with the
model its provider reported answering, and a gate pass names it in its reason;
a route whose responses named no model says so instead of repeating the
configured one. See [Preflight record](results.md#preflight-record) for the
record, verify and gate fields.

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
| `catalog init [DIRECTORY] [--providers LIST] [--replace]` | Create an ignored local workspace with `watch.json`, `approved.json`, `.env.production`, and `results/`. Without `--providers`, it asks once and Enter means all supported providers (`openai`, `anthropic`, `gemini`, `xai`, `openrouter`, `deepseek`, `qwen`, `typesafe`). For an existing workspace, it asks before rewriting only `watch.json`; `--replace` is the scripted equivalent and preserves approvals, keys, and results. |
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
