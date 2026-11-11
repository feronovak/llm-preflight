# CLI reference

**Last reviewed:** 2026-11-10 · **As of:** v2.24.0

From **2.22.2**, the terminal/Markdown summary labels mocks, excludes them from provider
rankings, withholds cost/value recommendations when evidence warnings block
a conclusion, and calls monetary figures estimates. A complete passing
candidate can still be compared when another candidate fails its tests.
Machine decision schemas and benchmark exit codes are unchanged.

Run `llm-preflight --help` for the installed version. The options below match this
version. A normal benchmark takes `config`, a benchmark JSON path. Standalone
commands such as `init`, `catalog`, `models`, `migrate`, `report`, `attest`, `verify` and
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
| `--audit-source PATH` | — | Statically find literal model IDs in a repository, with no provider request or application-code execution. Pricing findings are advisory. Each ID also gets a retirement verdict from the bundled snapshot of official deprecation pages, with date, provider-stated replacement and a ready `--quick --dry-run` command; `unknown` is not a verdict. An alias of a dated row takes that row's verdict (Anthropic, when all its dated rows agree) or is `alias_unmapped` (every OpenAI alias with dated rows). In a Git work tree it reads tracked and unignored files only; elsewhere, or when the work tree ignores `PATH`, every file under `PATH`. Git runs with repository-configured commands disabled. The text output starts with the decision and the exit code, then groups findings by model ID, retired first, capped at ten models and three locations each. An audit that reads no file is `inconclusive` and says why. Exit 0 unless `--ci`. |
| `--all` | off | With `--audit-source`, print every model and location, including references with unknown pricing and no retirement finding. `--json` is never capped. |
| `--change-plan [REF]` | `HEAD` | Inspect local Git changes against `REF`, including staged and untracked files, for literal model IDs and likely contract surfaces. A changed file it cannot read (no permission, a loop) is listed as unreadable and marks the plan incomplete instead of stopping it; so is a non-UTF-8 file with a `--audit-source` source suffix. A non-UTF-8 file with another suffix is not counted. It recommends no-spend commands; it never loads credentials, contacts a provider, or authorizes paid work. |
| `--contract-check` | off | Run configured accepted/rejected response fixtures, local image-fixture safety checks, and canonical tool-schema linting. It needs `validation_fixtures` (top level or inside a custom prompt) or `tools`; it never loads credentials or contacts a provider. |
| `--doctor` | off | Validate configuration, keys, model resolution, redacted credential provenance, and selected-model pricing coverage; no generation. It does not by itself block a benchmark. Reports each approved model's retirement status: a retired model is a failed check (exit 1 even without `--ci`); retiring, stale or an `alias_unmapped` model is a warning. |
| `--pricing-check` | off | Report selected direct models and OpenRouter routes with priced, undated, stale, or unknown pricing plus remediation; no generation. Its `pricing_coverage.ok` is false for stale or unknown prices; `pricing_coverage.enforcement_ok` is the exit/gate verdict and additionally fails undated pricing with `require_current_pricing: true`. |
| `pricing-refresh CONFIG [--write] [--offline] [--provider openrouter] [--max-age-days DAYS] [--json]` | off | Propose or atomically write refreshed OpenRouter catalog prices and return full selected-model coverage; no generation. `--provider` names the catalog to read; `openrouter` is the only choice and the default. |
| `--baseline PATH` | — | Compare a completed run with a saved result. With `--json`, embeds `baseline_diff` in one JSON document. Results with different output-contract evidence are incompatible; legacy artifacts without provenance are labelled `unknown`. |
| `--ci` | off | Return exit code 1 if a requested baseline/diff regression fails. With `--audit-source`, `--doctor` or `--dry-run`: 1 for a retired model, 3 retiring or stale, or an alias that could not be mapped (`alias_unmapped`); `--audit-source` also exits 3 when it read no file. The `--audit-source --ci` line for exit 0 says no referenced model has a retirement finding in the snapshot, and counts the model IDs that have no snapshot row and are not verified. |
| `--matrix` | off | Print model-by-test quality matrix instead of the normal report. |
| `--quick TEXT` | — | Run one ad hoc prompt; requires `--models`. |
| `--init [PATH]` | `benchmark.json` | Create a no-key mock config without overwriting a file. |
| `init [PATH] [--force]` | `benchmark.json` | Create a mock config, or use `--template provider` with explicit `--provider`, `--model`, `--api-key-env` (the name of the key environment variable, never its value), and optional config-relative `--env-file` reference. `init` refuses to overwrite an existing file unless you pass `--force`; `--force` still refuses a symbolic link. `--write-env-example` (provider template only) also writes `.env.example` next to the config with that variable name and no value, and refuses to replace an existing `.env.example`. Add `--interactive` to collect the config path, provider, model, key-variable name, and optional env reference without prompting for a secret. `--agent-instructions PATH` opt-in writes only the marker-delimited managed block in that file. `--check` requires that flag and exits nonzero when the block is missing or drifted; it writes nothing. |
| `--models LIST` | — | Comma-separated `provider:model` list for `--quick`. An unprefixed ID is accepted only for recognizable OpenAI IDs. |
| `--diff BASELINE CURRENT` | — | Compare two saved JSON result files; no benchmark run. |
| `--replay PATH` | — | Re-run the saved source configuration in a result artifact. A route the result masks is restored from the config at its `source_config_path` as that file is now, not as it ran; without that config the command exits 2. |
| `--changed-since PATH` | — | With discovery, run models absent from a prior catalog JSON. |
| `--catalog` | off | Discover and print selected models; no generation. Each `base_url` prints as scheme and host[:port], as in `--dry-run --json`. |
| `--tests LIST` | — | Comma-separated built-in/custom test selector; `agent-smoke` is the recommended five-check suite. |
| `--profiles LIST` | — | Compatibility alias for `--tests`. |
| `--dry-run` | off | Safe preview: print resolved work, cost estimate, and `smoke_eligibility`; no generation. A model is eligible only with compatible catalogue type, adapter evidence, current pricing, and declared request/cost limits. Non-eligible models are listed with a reason and next step; eligibility gates `catalog prepare`, does not block a reviewed bounded run of text models, and a live run refuses the models it lists as refused. Lists retirement verdicts and next commands after eligibility. The plan carries `budget_limits` (`max_requests`, `max_estimated_cost_usd` and `violations`), and the text plan prints `Limits:` and `Limit breach:` lines. A non-interactive dry run that breaks a limit prints the plan, then fails with the message and exit code 2 the live run gives for the same config (a request cap below the possible requests, a cost cap the estimate exceeds or with unknown pricing, or a `require_current_pricing` coverage gap); it writes no approval receipt. The interactive preview only shows the lines. With `--json`, each `models[].base_url` (and `catalog_candidates[].base_url` for catalog watch) prints only scheme and host[:port]; a path, query, userinfo or `;` parameter prints as `/[REDACTED]`, and an exact public provider route stays. A token in a host name stays visible. A base URL that is not http(s) with a plain host (for example `https://host;tok=1`) prints as `[REDACTED]`. Masking does not change the approval receipt hash, which still covers the unmasked plan; a receipt still reports `mismatch` when the plan changes. |
| `--approval-receipt PATH` | — | With `--dry-run`, write an expiring private local receipt bound to that exact plan. Requires a review note and timezone-qualified expiry; never authorizes paid work. |
| `--replace-approval-receipt` | off | Replace a receipt that already exists at the `--approval-receipt` path; without it an existing receipt is never overwritten. Requires `--approval-receipt`. |
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
| `catalog refresh WATCH_CONFIG` | Fetch provider metadata, classify catalogue entries, update the local snapshot, and report per-model `smoke_eligibility`. It makes no generation requests unless `--test` is given (see below). Optional legacy watch flags such as `--json`, `--snapshot`, and `--env-file` remain available. With `--write-config PATH --against APPROVED` it writes a benchmark config for newly discovered models (`--replace` overwrites an existing one). `--all-unapproved` writes every smoke-eligible unapproved model, and `--select-candidates` asks you on stdin to choose a small text-generation candidate set first. Both apply only together with `--write-config` and are silently ignored without it. |
| `catalog prepare WATCH_CONFIG --against APPROVED --output CANDIDATES` | Group unapproved `text-ready` candidates by provider, require an explicit model selection, then write a temporary benchmark plan containing only smoke-eligible rows. `text-candidate` models first use `catalog probe`; non-text, unpriced, unbounded, or unproven rows remain visible in refresh eligibility output. Use `--replace` only when deliberately rebuilding that plan. |
| `catalog probe WATCH_CONFIG [--models LIST] [--ledger PATH] [--no-env-file | --env-file PATH]` | Review `text-candidate` models, then make one explicitly confirmed, provider-native minimal request per selection. It uses the same explicit environment-file controls as benchmark runs. Results are saved locally in `.llm-preflight/capabilities.json` next to the watch config, or at `--ledger PATH`; response text and keys are never stored. |
| `catalog test WATCH_CONFIG --approved APPROVED --output CONFIG` | Write a runnable benchmark plan for permanent approved models, using the test settings in the watch config. |
| `CANDIDATES --interactive --approve-to APPROVED` | Run the single interactive benchmark flow, then offer passing models for approval. |
| `models approve PROVIDER:MODEL --from RESULT --approved APPROVED` | Explicitly approve one passing model from a saved result, optionally with `--note TEXT`. A route the result masks is restored from its `source_config_path` config; without it the command exits 2 and writes nothing. |
| `migrate CONFIG [--output PATH [--replace]] [--run] [--verify-approval-receipt PATH] [--output-dir DIR] [--env-file PATH \| --no-env-file] [--ci] [--json]` | Report, for each explicit `models` entry, whether the bundled retirement row names a provider replacement. No provider is called without `--run` and `discovery` is ignored with a warning. Without `--output` no file is written. With `--output`, which must be in the config's directory and cannot be the source config, the replacement rows are written as a candidate config (one row per replacement; a new row copies only `provider`, public `base_url`, `api_key_env` and `api_version`; a replacement already in your config is written as your own row, with its prices, unless it sets `headers` or a custom `base_url`, so only a public `base_url` is ever written or printed; smoke settings are included; an existing file needs `--replace`) and the report adds the dry-run `plan`, `approval` (state `missing`) and the commands to record a receipt and run the smoke. With `--run`, which needs `--output` pointing at the candidate already written, `migrate` runs the bounded smoke once, only if all hold: the candidate re-derived now equals the file on disk; the plan is rebuilt from that file the way `--dry-run` loads it; the receipt named by `--verify-approval-receipt` verifies as `recorded` with `bounds` equal to the plan's; `maximum_estimated_cost_usd` is not null; the budget check passes. Otherwise no env file is loaded and no provider is called. `--run` is the authorizing act: the receipt is a required precondition only and still has `authorizes_paid_run: false`. `--verify-approval-receipt` without `--run` only reports `approval.state` (`missing`, `recorded`, `expired`, `mismatch`, `invalid`, `candidate_changed` or `unbounded`); a missing or unreadable receipt is reported, not raised. After a smoke the report adds `smoke` and `paid_requests_made`, and the run's decision replaces the decision of each row whose replacement was written on the same route; a row that kept its own route (custom `base_url` or `headers`) keeps its decision. `--run` exits like `--ci`: 1 for `fail`, 3 for `inconclusive`. `--env-file`, `--no-env-file` and `--output-dir` apply to `--run` only; `--replace` cannot be combined with `--run`. A config with only `prompts` stops with `select a custom prompt before running the benchmark`. A budget excess, a config value of the wrong type (which can surface after a provider request was already sent; the message says so) and a config with only `prompts` stop with exit 2 and no report (nothing is printed under `--json`). `paid_requests_made` counts provider attempts sent, retries included, including a request the provider rejected with 401 or 403, and not a request that stopped for a missing API key. After a smoke, `next_steps` no longer offer the record or run commands: a `pass` says that adopting the replacement is your step, while `fail` or `inconclusive` give the reason and the saved result and say not to adopt it. The smoke writes only its result files. A candidate file that is absent or differs from the derived one reports `candidate_changed` and `next_steps` give the rewrite command (`migrate CONFIG --output PATH --replace`) instead. Per model the `outcome` is `candidate`, `replacement_in_config`, `no_named_replacement`, `replacement_unusable` (the replacement is itself retired or retiring; the chain is not followed), `alias_unmapped` (the ID is an alias without a safe mapping to one snapshot row), `snapshot_stale`, `route_base_url` (the row sets a custom `base_url`), `route_headers` (the row sets `headers`; add the replacement by hand) or `not_affected`. A replacement with status `unknown` is reported as `unknown`, never active. The decision is the worst row decision. Exit 0 unless `--ci`: then 1 for `fail`, 3 for `inconclusive`; 2 for a usage or config error. Secret-shaped text is redacted; with `--output`, a redaction that would replace a non-string value (for example a schema property named `token`) is a config error naming the path, and without `--output` it is a warning and no candidate. Control characters in names are escaped. `--json` keys: `schema_version`, `kind`, `decision`, `models`, `candidate_config`, `plan`, `approval`, `smoke`, `paid_requests_made`, `warnings`, `next_steps`. |
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

`watch-new` and `approve-model` are compatibility aliases for existing scripts. `--test` runs a benchmark of the new candidates against the approved models and sends generation requests unless `--dry-run` is also given; like `--write-config` and `--interactive`, requires `--against APPROVED`. `watch-new` takes the same `--write-config`, `--replace`, `--all-unapproved` and `--select-candidates` flags as `catalog refresh`.
They expose legacy options and are not the recommended workflow. See
[Model watch and approval](../guides/model-catalog.md) for the complete tutorial.
