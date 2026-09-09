# Configuration reference

**Last reviewed:** 2026-09-09 · **As of:** v2.14.0

Configurations are JSON. A config requires `models` or `discovery`, and either
one top-level `prompt` or one or more named `prompts`.

## Top-level keys

| Key | Default | Meaning |
|---|---:|---|
| `name` | `llm-benchmark` | Label stored in results. |
| `env_file` | adjacent `.env.production` | Optional non-empty relative path to an existing env file within the configuration directory. It records a path only; it never copies secrets. Shell values take precedence. |
| `prompt` | — | Single prompt when not selecting test profiles. |
| `models` | `[]` | Explicit model objects or alias strings. |
| `discovery` | `[]` | Provider-catalog sources. |
| `prompts` | `[]` | Named reusable custom prompt tests. |
| `profiles` | — | Built-in/custom test selector; use `all` for built-ins. |
| `repetitions` | `5` | Measured runs per model for a single top-level prompt. |
| `suite_repetitions` | `1` | Repetitions of each case in selected test profiles. |
| `warmups` | `1` | Per-model warmup calls; per profile when tests are selected. |
| `concurrency` | `1` | Parallel calls for a top-level prompt. |
| `timeout_seconds` | `120` | Provider connect/read timeout, not a total streaming deadline. |
| `request` | see below | Shared request options. |
| `validation` | non-empty | Top-level response checks. |
| `validation_fixtures` | — | Optional local accepted/rejected responses used by `--contract-check`; when set, include at least one `pass` and one `fail` expectation. |
| `tools` | `[]` | Optional canonical tool definitions checked locally for portable names, descriptions, and parameter schemas. They are not sent to providers by this release. |
| `presets` | `[]` | Shared provider-aware presets. |
| `save_responses` | `false` | `true`, `false`, or `failures`. |
| `stop_on` | none | `api-error`, `test-fail`, or `any-fail`. |
| `fail_fast` | `false` | Legacy boolean equivalent to `stop_on: any-fail`. |
| `max_requests` | — | Reject a run whose retry-expanded request maximum exceeds this. |
| `max_estimated_cost_usd` | — | Reject a run whose retry-expanded cost exceeds this. |
| `require_current_pricing` | `false` | Reject a paid run when any selected direct model or OpenRouter route has unknown, undated, or stale pricing. Mock fixtures are exempt. Use `--pricing-check` for remediation before running. |
| `aliases` | `{}` | Named model definitions. |
| `environments` | `{}` | Named shallow config overlays selected with `--env`. |
| `approvals` | `[]` | Local `models approve` audit entries; ignored by benchmark runs. |

## `request`

| Key | Default | Meaning |
|---|---:|---|
| `temperature` | provider default | Sampling temperature, unless the model disables it. |
| `max_output_tokens` | `256` | Maximum generated tokens for native providers. `max_tokens` is accepted for compatibility. |
| `system_prompt` | — | Shared system instructions. |
| `input_images` | — | Explicit local PNG, JPEG, WEBP, or GIF fixtures for supported image-to-text routes. |
| `provider_options` | `{}` | Provider request body fields; one object or `{all, provider}` maps (`openai_compatible` is valid for a custom OpenAI-style endpoint). |
| `retry` | two attempts | `true` or an object described below. |

For the `mock` provider only, `response` supplies the returned text when it is
not set on the model.

`input_images` is a non-empty list of objects with either a config-relative
`path` and matching `mime_type`, or a caller-provided base64 `data_url`. Paths cannot leave the configuration directory. The
tool checks the file header, dimensions, a 10 MiB byte limit, and a 20-million
pixel limit before sending a request. It records only the path, MIME type,
dimensions, source type, and a content hash in the resolved configuration and
results; image bytes are read and encoded only while making a supported provider request.
Use it with OpenRouter/OpenAI-compatible chat routes or Gemini. Other adapters
reject image inputs rather than silently dropping them.

`retry` accepts `max_attempts` (2), `initial_delay_seconds` (0.25),
`max_delay_seconds` (4), `backoff_multiplier` (2), `jitter_seconds` (0.1),
and `retry_on` (`rate_limit`, `timeout`, `transient_provider`, `network`).

## `models` and `discovery`

A model requires `model`; `provider` defaults to `openai_compatible`. Useful
optional model fields are `name`, `base_url`, `api_key_env`, `api_version`,
`headers`, `input_cost_per_million`, `output_cost_per_million`,
`cached_input_cost_per_million`, `pricing_tiers`, `max_tokens_parameter`, and
`supports_temperature`. When setting explicit prices, also set
`pricing_metadata` with at least `source` and ISO-8601 `as_of`; otherwise
`--pricing-check` reports the price as undated. `pricing_tiers` is an ordered per-request price list;
each tier may set `up_to_input_tokens` before the next tier applies.
`official snapshot` is reserved tool-owned provenance: use another source label
for a user-supplied price, because a matching bundled snapshot is refreshed on
package upgrade.
`capabilities` is advanced provider metadata; catalogue refresh and probes
maintain it automatically, so most users should not set it manually. Mock
models also accept `response`, `latency_seconds`, and `ttft_seconds` for
deterministic local fixtures.

Supported provider names are `openai`, `anthropic`, `gemini`, `xai`,
`openrouter`, `openai_compatible`, and `mock`. A discovery object requires
`provider` and positive `limit`; it can also set case-insensitive regex
`include`/`exclude`, `sort`, `output_modalities`, `require_parameters`,
`base_url`, `api_key_env`, `api_version`, and `headers`. `output_modalities`
and `require_parameters` are OpenRouter catalog filters.

## `prompts`, validation, aliases, and environments

Each prompt requires a unique `name` that does not reuse a built-in test-pack
name, and either non-empty `prompt` or a relative
`prompt_file` within the config directory. Optional keys are `description`,
`system_prompt`, `request`, `validation`, `validation_fixtures`, and `presets`.

Validation supports non-empty `contains`, `regex`, `exact`, `golden`, `json_schema`,
`json_set`, `json_object`, `json_array`, `exact_count`, `allowed_values`, `numeric_answer`,
`numeric_tolerance`, `max_chars`, and `no_markdown`; an absent custom validation
means non-empty output. `exact_count` requires `json_array`, and
`numeric_tolerance` requires `numeric_answer`. `json_schema` is strict raw JSON
by default. Set `"allow_fenced_json": true` alongside it only when the deployed
consumer accepts exactly one complete Markdown-fenced JSON block; surrounding
prose is allowed, but multiple blocks and unfenced prose objects still fail.
`consumer` may declare the deployed JSON consumer as `raw_json`, `fenced_ok`,
`prose_tolerant`, `first_fenced_block`, or `first_json_value`; it records
contract-only failures without weakening the configured validator, and rejects
a response the declared consumer cannot parse even if that validator otherwise
passes. The two `first_*` policies intentionally model consumers that choose
the first matching payload; use them only when that is the deployed behavior.
`json_set` checks an object key as an unordered array with no duplicate values,
for example `{"json_set":{"key":"exclude","expected":[2,3,4]}}`.
`golden` is a deterministic trimmed,
case-insensitive expected-answer check.
Unknown validation keys are rejected before a benchmark can run. The supported
JSON Schema subset handles object `required`/`properties`, arrays and item
limits, primitive `type`, and `enum`. Every schema node must declare one of the
supported types; a missing or misspelled type is a configuration error rather
than a silently ignored constraint.

`aliases` maps a name to a model object; use its name in `models`. An
`environments` item is a shallow overlay—its top-level keys replace the base
config, including a complete `request` object when supplied.

See [configuration examples](configuration.md) and the checked-in example JSON
files for complete runnable examples.

## Contract fixtures and tools

`validation_fixtures` exercises the configured deterministic validator without
loading credentials or contacting a provider. Each item has exactly `name`,
`response`, and `expect`, where `expect` is `pass` or `fail`. A fixture list
must contain at least one of each expectation, so it can catch an overly weak
contract as well as an overly strict one. Put fixtures at the top level for a
top-level prompt, or beside a named custom prompt and select it with
`--prompt`. A benchmark refuses to start before provider work when configured
top-level fixtures fail.

`tools` is a local canonical declaration, not an implicit tool-calling request.
Each entry has exactly `name`, `description`, and object-shaped `parameters`.
The supported schema subset is `type`, `properties`, `required`, `items`,
`enum`, and boolean `additionalProperties`; unsupported keys are rejected to
avoid claiming portability the providers may not share.
