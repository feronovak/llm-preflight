# Result JSON schema

**Last reviewed:** 2026-09-30 · **As of:** v2.19.0

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
| `provenance` | Secret-safe evidence identity. It includes versioned hashes of the effective configuration, contract, and resolved routes; reuses the pricing fingerprint; records per-prompt hashes and declared request/cost caps; and combines these in `evidence_sha256`. It never exposes routes, headers, prompts, or secrets through this field. |
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
`retry_count`, `retry_reasons`, timing, token counts, cost inputs, and an
optional response or response preview according to `save_responses`.

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
