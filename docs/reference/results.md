# Result JSON schema

**Last reviewed:** 2026-10-09 · **As of:** v2.19.2

`llm-preflight CONFIG --json` writes one result object to standard output. Saved
`results/*.json` files use the same schema. The current `schema_version` is
`1`; integrations should reject an unknown major schema version rather than
guessing its meaning.

## Offline reports

Render a saved result without contacting a provider:

```bash
llm-preflight report results/run.json --output report.html
llm-preflight report results/run.json --format markdown
```

The renderer supports schema version 1 and rejects unknown major versions. It
recomputes the run decision from the result evidence, shows baseline
comparability separately, and reports contract validity, request count,
latency, usage, estimated cost, and pricing status/source/date. It never embeds
prompts, responses, credentials, local paths, host details, raw error text, or
custom run labels. Model identifiers are escaped and constrained before display.
The HTML uses inline CSS only; it makes no network requests. Small samples are
directional and do not establish a universal model ranking.

## Dry-run plan fields

`llm-preflight CONFIG --dry-run --json` prints a plan instead of a result and
does not create an artifact. Its additive `smoke_eligibility` field contains a
summary (`discovered`, `needs_review`, and `eligible`) and one entry per
resolved model. Each entry has `provider`, `model`, `catalog_type`, `eligible`,
and a stable `reason`: `eligible`, `catalog_evidence_required`,
`probe_required`, `adapter_evidence_required`, `incompatible_catalog_type`,
`unknown_pricing`, `undated_pricing`, `stale_pricing`, or
`bounded_limits_required`. Agents must use this evidence rather than infer
whether a newly discovered ID is safe to include in a paid smoke.
Eligibility confirms that request and cost caps exist. The paid-run budget gate
then enforces those caps against the dry-run's retry-expanded requests and
maximum estimated cost; eligibility itself is not a cost estimate.

## Top-level fields

| Field | Meaning |
|---|---|
| `run_id`, `timestamp`, `benchmark` | Unique run identifier, UTC timestamp, and config name. |
| `prompt_name`, `prompt_sha256`, `prompt_chars` | Selected custom-prompt name when applicable, plus safe prompt identity metadata. |
| `selection` | The run flags that shaped the config, by name only: `prompt` (`--prompt`), `tests` (`--tests` or `--profiles`, with legacy names mapped, each once, sorted and comma-joined), `environment` (`--env`), `migration_check` (`--migration-check`) and `smoke` (`--smoke`), plus `repetitions`, how many times the run sent each prompt (`suite_repetitions` for test profiles, `repetitions` otherwise; 1 under `--smoke`). Unused flags are `null` or `false`. An env file only supplies credentials, so neither its path nor its contents appear. Results written before 2.22.0 do not have it. |
| `ci` | The GitHub Actions run the check ran in, read from the environment when the run started: `repository`, `workflow`, `runId`, `runAttempt`, `commit` and `serverUrl`, from `GITHUB_REPOSITORY`, `GITHUB_WORKFLOW`, `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, `GITHUB_SHA` and `GITHUB_SERVER_URL`. Names and numbers only, never a token. `null` outside GitHub Actions or when the set is incomplete or malformed. Results written before 2.22.0 do not have it. |
| `settings` | Effective repetitions, warmups, concurrency, timeout, request options, and selected profiles. |
| `environment` | Hostname and Python version that produced the evidence. |
| `models` | One result object per attempted model, in run order. |
| `total_input_tokens`, `total_output_tokens`, `total_estimated_cost_usd` | Reported token subtotals including warmups. Total cost is `null` whenever any represented request lacks usable usage or pricing. |
| `priced_cost_usd`, `cost_confidence`, `unpriced_models` | Known cost subtotal (`null` if none is known), coverage (`complete`, `partial`, or `unknown`), and models with missing usable prices. Missing usage alone does not make a model unpriced. |
| `cost_coverage` | Additive counts across measured and warmup samples: `known_requests`, `missing_usage_requests`, `missing_price_requests`, and `unobserved_retry_requests`. Missing usage includes malformed counts. The two missing-evidence counts can overlap on one request. Retry attempts have no retained usage and prevent a complete total; known final-response cost remains in the subtotal. |
| `usage_coverage` | Counts of requests reporting usable `input_tokens` and `output_tokens`, separately. Compare each with the sum of measured and warmup request counts before treating its token subtotal as complete. |
| `pricing_warnings` | Pricing freshness or availability warnings. |
| `pricing_coverage` | Coverage for every selected direct model and OpenRouter route, including `priced`, `undated`, `stale`, or `unknown` status, source, source URL, as-of date, stable warning code, remediation, and whether a mock fixture is pricing-exempt. The summary separates all `selected` rows from `billable` rows and `exempt` mock fixtures, so `priced` never counts a mock. `ok` is false for stale or unknown pricing; `enforcement_ok` additionally becomes false for undated pricing when `require_current_pricing` is enabled, and is the paid-run/CI gate verdict. |
| `configuration_warnings` | Non-blocking comparability warnings implied by the selected configuration, such as including Anthropic with the `json` preset. Anthropic receives no equivalent native JSON-mode request, so those results are not directly comparable to providers that do. |
| `pricing_ledger`, `pricing_fingerprint` | Redacted resolved per-model prices/provenance used by this run and their stable SHA-256 identity. These are additive fields in schema version 1. |
| `provenance` | Secret-safe evidence identity. It includes versioned hashes of the effective configuration, contract, and resolved routes; reuses the pricing fingerprint; records per-prompt hashes and declared request/cost caps; and combines these in `evidence_sha256`. It never exposes routes, headers, prompts, or secrets through this field. `provenance.prompts` lists the prompts the run sent, each once, and nothing else. A profile run lists every case of the selected profiles (a custom prompt is one case under its own name) and not the top-level prompt. Any other run lists only its top-level prompt, or under `--prompt` only the selected prompt; the configured `prompts` list is not listed when it did not run. Each entry has `name`, `sha256` and `chars` of the prompt text, and `request_sha256`, a canonical hash of the request options sent with it: the run's `request` (or the default `temperature` 0 and `max_output_tokens` 256), merged with a test's own `request` and expanded `presets`, and its `system_prompt`. Runtime-only keys are left out, secret-like values are redacted before hashing, and each input image counts by its content digest and MIME type, never its path. |
| `decision` | Additive agent decision object with its own `decision.schema_version`. It exposes `pass`, `fail`, or `inconclusive`, an exact safe next command, and verbatim blocking warnings. See [Agent decision contract](decision.md). |
| `source_config` | Redacted input configuration, retained for replay and audit. |
| `source_config_path` | Absolute source configuration path when available; `--replay` uses its adjacent `.env.production` by default. |

## Model result

In 2.18.0, `provenance.validator_version` identifies the output-schema
enforcement semantics (`output-schema-3`). This revision distinguishes JSON
booleans from numbers recursively in object/array enum members; numerical
equivalents such as `1` and `1.0` remain equal. All structured-output parsing
policies reject non-JSON `NaN` and `Infinity` constants and numbers whose
exponent overflows the finite numeric range, even in fields without numeric
schema rules. Decimal values that would round into a different number are
rejected rather than compared inaccurately; oversized integers produce an
invalid-JSON result instead of a decoder error. Prose parsing skips malformed
outer values without accepting their nested objects as separate results. The
identifier is independent
of the package
version and is included in contract/evidence fingerprints. A semantics change
requires a new identifier. Baselines with different known identifiers are
incompatible; matching contract hashes without known semantics are `unknown`.
Different contract hashes remain incompatible, including comparisons with
legacy artifacts. Older artifacts are never backfilled with the new identifier.

Each `models[]` object identifies the resolved provider/model and includes:

| Field | Meaning |
|---|---|
| `name`, `provider`, `model` | Human label and resolved model identity. |
| `observed_model` | The model the provider's responses said answered, across measured and warmup requests: a string when they agree, the sorted distinct strings when they disagree, and `null` when no response named one. It is read from the OpenAI-compatible `model` field (OpenAI, OpenRouter, xAI, DeepSeek, Qwen, Z.ai and custom endpoints), the Anthropic `message_start` message's `model`, the Gemini `modelVersion` and the OpenAI Responses `model`. A value that is not a non-empty printable string of at most 256 characters is ignored, never repaired. It is a measurement, not configuration: it is not part of `provenance`, so no fingerprint depends on it. Results written before 2.22.0 do not have it. |
| `summary` | Measured requests, validation, timing, usage, cost, retries, and failures. |
| `warmup_summary` | The same metrics for warmup requests; exclude it from your quality gate. |
| `samples` | Per-request observations for a plain prompt, subject to `save_responses`. |
| `profiles` | Per-test-pack results instead of top-level samples when using `--tests`. |

`summary` fields include `requests`, `successful`, `failed`, `success_rate`,
and `valid_output_rate`. The last field is the application-quality gate: a
response can be successful at HTTP/API level yet invalid for its evaluator.
`latency_seconds`, `ttft_seconds`, and `output_tokens_per_second` are objects
with `mean`, `min`, `p50`, `p95`, and `max` (except where a metric only has a
meaningful subset). They are `null` when unavailable. `estimated_cost_usd` is
`null` when any sample lacks usable usage or pricing. Each summary also includes
`priced_cost_usd`, `cost_coverage`, and `usage_coverage` with the same meanings
as the run fields, scoped to that summary. A zero-request summary has a zero
cost and zero coverage counts; it creates no missing-evidence warning.
Token fields sum only valid reported counts; a partial subtotal is not a full
usage total. Summaries also include `cached_input_tokens` for cache reads and
`cache_write_input_tokens` for reported cache writes. These counts partition
total input tokens, rather than adding to them; output usage includes billable
reasoning tokens. The pricing ledger retains
`cache_write_input_cost_per_million` and any applicable per-request tiers.

Absent usage is distinct from explicitly reported zero usage. Usable counts are
nonnegative finite integral numbers, excluding booleans and numeric strings.
Missing or invalid input/output counts make cost unavailable; an explicitly
reported invalid cache read/write count, or a combined cache count above total
input, also makes it unavailable. Reported writes need a known write price.
Missing optional cache
counts use the ordinary uncached rate. Gemini requires a reported candidate
count and adds a valid reported reasoning count; an omitted optional reasoning
count adds nothing.

A billable run that passes its output contract but lacks complete cost evidence
is `inconclusive`. Request or contract failures retain their failure verdict
and include evidence warnings. Complete zero-token evidence remains a known
zero estimate. Mixed evidence preserves the known subtotal and never implies
that the unavailable total is zero.

Legacy schema-v1 artifacts without `cost_coverage` cannot establish cost
completeness. Readers retain the saved data, mark its cost evidence unverified,
and show cost as unavailable in reports. A billable result with unverified
legacy evidence is inconclusive unless a failure takes precedence. Baseline
comparisons suppress cost deltas and expose `cost_comparability: unknown` for
legacy or incomplete saved evidence, independently of contract comparability.

`output_tokens_per_second` is also `null` when the stream was not observably
incremental — fewer than two text chunks, or a generation window under 100 ms.
Some providers buffer the whole response server-side and burst it at the end;
the post-TTFT window then measures transport, not generation, and reporting a
rate would inflate throughput by orders of magnitude.

Failure and retry diagnostics are safe aggregates: `failure_reasons`,
`failure_categories`, `retry_count`, `retry_reasons`, and `failure_hints`.
Every summary includes `contract_only_failures`, `consumer_rejections`,
`golden_accuracy`, and `golden_confusion`. The latter two are `null`/empty when
the run has no golden cases. A consumer rejection fails the benchmark even when
the configured validator otherwise passes; a contract-only failure is rejected
by the configured contract but accepted by the declared consumer parser.

Golden samples include normalized `golden_expected`, `golden_observed`, and
`golden_valid`. Consumer-profile samples include `consumer_valid_output`,
`contract_only_failure`, and `consumer_rejection`.

## Samples and profile cases

A plain-prompt `samples[]` entry includes `ok`, `valid_output`,
`quality_score`, `evaluation_error`, `failure_category`, `attempts`,
`retry_count`, `retry_reasons`, timing, token counts, cost inputs,
`observed_model` (that request's reported model, with the same string, list or
`null` rule as the model result), and an optional response or response preview
according to `save_responses`.

For a profile run, `profiles[]` contains `name`, `description`, `summary`, and
per-case `samples`. Each sample has `case_id`; concurrency-health samples also
have `concurrency`.

Do not parse terminal tables. Prefer `valid_output_rate` for application
quality, `success_rate` for transport reliability, and `failure_category` for
automation decisions. Treat absent optional fields and `null` metrics as
unknown rather than zero.

## Baseline comparison JSON

`llm-preflight --diff BASELINE CURRENT --json --ci` writes a separate comparison
object: `ok` plus `models[]`. A compared row exposes
`latency_p95_delta_seconds`, `success_rate_delta`, `valid_output_rate_delta`,
`cost_delta_usd`, and `regressions`. An added model has `status: "added"` and
no regression by itself. A non-empty `regressions` list makes `--ci` exit 1.

## Source audit JSON

`llm-preflight --audit-source PATH --json` writes a separate, uncapped audit
object. `root` is the resolved path; in it and in each reference `path`, a
byte of a name that is not UTF-8 is written as a backslash escape such as
`\xff`. `network_accessed` is always `false`,
`files_scanned` counts the selected files that were read as UTF-8 text,
`files_unreadable` the selected files that were not (such as UTF-16 files or
files the user may not read), and `file_selection` names how
they were selected: `git` (tracked files, including initialized submodules,
plus untracked files `.gitignore` does not exclude, including those of an
untracked nested repository), `filesystem` (every file under the path) or
`file` (the named file). `file_selection_reason` is `null` except in
`filesystem` mode, where it says why Git did not select the files: Git is not
installed, Git could not list files (with Git's first error line, such as
"not a git repository"), or the path is ignored by its enclosing repository.
Each `references[]` entry has `path`, `line`,
`provider`, `model`, pricing `status` and `confidence`, and a `retirement`
verdict. `findings` lists the references with unknown pricing or a retired,
retiring or stale verdict. `decision` (`fail`, `inconclusive`, `pass` or
`none`) is the worst retirement decision across all references and drives
the `--ci` exit code. When `files_scanned` is 0, including when every
selected file was unreadable, the decision is `inconclusive`: an audit that read nothing has no evidence. `next_commands`,
`retirement_snapshot`, `confidence` and `notes` complete the object.

## Preflight record

`llm-preflight attest RESULT` writes a portable record of a saved
schema-version-1 result. The record is an
[in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
with the
[test-result v0.1 predicate](https://github.com/in-toto/attestation/blob/main/spec/predicates/test-result.md),
so `actions/attest` can sign it unchanged. It proves that a named check ran on
a contract and its routes; it does not certify production behaviour.

| Field | Meaning |
|---|---|
| `_type`, `predicateType` | `https://in-toto.io/Statement/v1` and `https://in-toto.io/attestation/test-result/v0.1`. |
| `subject` | Two ResourceDescriptors with a `sha256` digest: the benchmark config (`annotations.role: "config"`) and the saved result (`"result"`). A name is relative to the working directory, or the bare file name for a file outside it. |
| `predicate.result` | The saved decision, copied and never recomputed: `pass` is `PASSED`, `inconclusive` is `WARNED`, `fail` is `FAILED`. |
| `predicate.passedTests`, `warnedTests`, `failedTests` | One name per model and test, such as `openai:gpt-4.1-mini/strict-json-extraction`, or per model and prompt without tests (`provider:model/config-prompt`). In an inconclusive run every test that did not fail is listed as warned. |
| `predicate.url` | The GitHub Actions run attempt, `SERVER/OWNER/REPO/actions/runs/ID/attempts/N`. Absent for a local record. |
| `predicate.configuration` | Four ResourceDescriptors whose `sha256` digests are the result's `provenance` fingerprints: `llm-preflight/contract` (`annotations.validatorVersion`), `llm-preflight/routes` (`annotations.routes`: `provider`, `model`, `pricingAsOf` and `observedModel` for each resolved route; `observedModel` is the result's `observed_model` for that route, and `null` for a result without one), `llm-preflight/pricing`, and `llm-preflight/evidence`. |
| `llm-preflight/evidence` annotations | `checkedAt` (the run's timestamp, which freshness counts from), `runId`, `decision` (the result's decision without `safe_next_command`, which names a local path), the full `provenance`, `requests`, `selection` (the result's `selection` as `prompt`, `tests`, `environment`, `migrationCheck`, `smoke` and `repetitions`; `null` for a result without one), `costUsd`, `costConfidence`, `retirementSnapshot`, `claimsNotMade` (production behaviour, accuracy beyond the declared validators, safety, other accounts or regions), `origin` (`github-actions` or `local`), `ci` and `attestedBy`. |
| `ci` | The result's run-time `ci`, copied only when `attest` runs in the same GitHub Actions run: the same `repository`, `serverUrl`, `runId` and `commit` in its own environment. Otherwise `null`, the origin is `local`, and `attest` says why: no identity at all, a result that records none (run outside GitHub Actions or before 2.22.0), a malformed one, another run, or an `attest` outside the run. `attest` refuses a partial or malformed set of `GITHUB_*` variables in its own environment. |

`attest` refuses a result without schema-version-1 provenance, provenance that
does not match its `evidence_sha256`, and a result it could not attest
consistently, such as a `pass` decision without complete cost confidence.
`attest --json` prints `path`, `record` and `origin_reason`, which says why
a record is local and is `null` for a GitHub Actions record.

`verify`, `gate` and the card read a record file of at most 1 MiB, nested at
most 64 levels deep; any other file is refused before it is judged.

### Verify JSON

`llm-preflight verify RECORD --json` reports integrity and freshness as
separate objects; neither implies the other.

- `integrity.ok` and `integrity.problems`: statement type, predicate type,
  subject and descriptor shape, the descriptor digests against the embedded
  provenance and its `evidence_sha256`, the result against the decision,
  the GitHub identity against `predicate.url`, and a `checkedAt` that is not
  after today. A `PASSED` record must come from a `pass` decision with
  complete cost confidence, no blocking warnings, and passed tests only.
  Each route's `provider`, `model` and `observedModel` must be a non-empty,
  printable string of at most 256 characters. A record is untrusted input,
  so text output shows any non-printable character in a record string or
  file name as its backslash escape (`\x1b`, `\n`), even when integrity
  fails; JSON output keeps the value, JSON-escaped. A string that is not
  valid Unicode text, such as a lone surrogate written as `\udcff` or a file
  name that is not UTF-8, is shown as its backslash escape in text, JSON and
  MCP output alike, so every report encodes as strict UTF-8.
- `integrity.subjects[]`: `name`, `role` and `state` (`matches`, `differs` or
  `absent`). Each subject is looked up relative to the working directory, then
  beside the record. A result that `differs` breaks integrity; a config that
  differs is reported only, because a later edit does not make the record
  dishonest. Only `verify` and the card, which ask about a specific result
  file, compare subjects; the gate never reads them, because a pull request
  controls the files in its tree.
- `freshness`: `state` (`fresh`, `stale`, `superseded` or `unknown`),
  `checked_at`, `age_days`, `max_age_days`, `valid_until` and
  `retired_routes`. A record stays fresh through `valid_until`, `checkedAt`
  plus `--max-age-days` (default 30). It is `superseded` once the verifier's
  own retirement snapshot lists a checked route as retired.
- `routes[]`: `provider`, `model` and `observed_model` for each recorded
  route; `observed_model` is `null` when the record has none.
- `repository` and `server_url`: the record's GitHub Actions repository and
  server, `null` for a local record.
- `retirement_snapshot` (the verifier's own snapshot date), `result`,
  `origin`, `url` and `signature`, which is always "not checked here — use gh
  attestation verify".

### Gate JSON

`llm-preflight gate [CONFIG] --records PATH... --json` decides offline whether
the current tree has a fresh passing record. It fingerprints `CONFIG` as a run
under the gate's selection flags would record it (`--env`, `--smoke`,
`--prompt`, `--tests` or `--profiles`, `--migration-check`; by default a
default run),
with no credentials and no provider request, and reads each record file and
every `*.preflight.json` under each directory.

| Field | Meaning |
|---|---|
| `decision` | `pass` (exit 0), `blocked` (exit 1) or `undecided` (exit 3). |
| `reason_code` | `fresh_pass`; when blocked, `no_record`, `foreign_record`, `selection_changed`, `contract_changed`, `routes_changed`, `prompt_changed`, `stale`, `superseded`, `inconclusive_record`, `failed_record`, `inconsistent_record`, `committed_record` or `local_record`; when undecided, `config_error`, `repository_unknown` or `record_error`. |
| `why`, `next` | The reason in one sentence and the numbered next steps, identical to the text output. |
| `records[]` | One entry per record with its own `verdict` (`pass` or a reason code), `reason`, `path`, `result`, `origin`, `run_id`, `repository`, `server_url`, `checked_at`, `age_days`, `valid_until`, `tests`, `blocking_warnings`, `retired_routes`, `routes` (as in verify JSON), `selection` (the record's, `null` when it has none), `contract_sha256` and `routes_sha256`. Fields the gate could not read are `null`, or empty lists. |
| `selection` | The selection the gate requires, in the record's form, with `repetitions` from the current config under it (`null` when the config cannot be fingerprinted). |
| `repository`, `server_url` | The repository whose records count, from `--repository OWNER/NAME`, else `GITHUB_REPOSITORY`, and its server, from `GITHUB_SERVER_URL`, else `https://github.com`. Both are `null` when no repository is known, or when `--repository` and `GITHUB_REPOSITORY` name different repositories; the gate is then `undecided` with `repository_unknown`. |
| `contract_sha256`, `routes_sha256` | The current tree's fingerprints under that selection; `null` when the config cannot be fingerprinted. |
| `config`, `max_age_days`, `retirement_snapshot`, `signature`, `network_accessed` | Inputs and the verifier's snapshot; `network_accessed` is always `false`. |

The newest record by `checkedAt` that comes from the expected repository,
ran the gate's selection, matches both fingerprints and the prompts the
config sends now (names, text and request options, in any order), and
carries a GitHub Actions identity decides; on equal age a non-passing record
wins. A record tracked by Git, a local record, a record from another
repository or server (`foreign_record`; owner, name and host compare without
regard to case, as GitHub does), an inconsistent record, a record for
another selection or another number of repetitions per prompt (or one that
records none), a record for other fingerprints and a record for other
prompts (`prompt_changed`, also for a record whose prompts carry no
`request_sha256`) never decides. The gate names the selection, and only a
record that ran exactly that selection counts: a record of a narrower run,
such as `--tests` with one cheap test or a `--smoke` run, cannot pass a gate
that requires a default run. The gate judges a record by its internal
consistency only, never by the files it names. One unreadable record makes
the gate `undecided`, because it could have been the newest; so does a
record that fails its integrity check when its unproven `checkedAt` is
missing or not older than the record that would decide. A config with `discovery`
cannot be fingerprinted offline and is `config_error`, as is a gate
selection the config cannot satisfy, such as an unknown `--prompt`. Give the
gate the selection flags CI passes to the run; an env file is not a selection
and needs no flag.
