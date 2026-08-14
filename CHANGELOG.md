# Changelog

All notable changes to this project are documented here.

## Unreleased

### Fixed

- Treat a model with complete per-request pricing tiers as priced for coverage
  and decision purposes, matching the estimator's tier selection.
- Omit the unsupported `temperature` parameter for `claude-opus-5` by default.
- Compact HTTP failures in the terminal quality gate so provider error bodies
  and request IDs do not expand report tables.
- Replace the retired `gemini-3.5-flash` in the cross-provider example and
  ignore generated `.llm-preflight/` workspace data.

## 2.7.1 - 2026-08-13

### Added

- Add an additive, independently versioned agent decision object with pass,
  fail, and inconclusive states; verbatim blocking warnings; and a safe next
  command in result JSON and MCP preflight responses.
- Add opt-in marker-delimited agent instruction blocks from `init`, including a
  non-mutating drift check.

### Changed

- Make mock-only results inconclusive, prevent model approval unless the whole
  result decision passes, and use exit code 3 for inconclusive evidence.
- Distinguish API failures from contract failures in agent decisions and point
  their safe next commands at setup diagnostics or a no-request plan review.

### Breaking

- A mock-only benchmark no longer exits successfully, and automation must
  distinguish exit code 3 (inconclusive) from exit code 1 (failed).

### Fixed

- Make the TestPyPI fresh-install smoke check accept the intentional exit code
  3 from its mock-only benchmark.

## 2.6.0 - 2026-08-11

### Added

- Add full selected-model pricing coverage with `priced`, `undated`, `stale`,
  and `unknown` states, stable machine-readable reason codes, and remediation.
- Record a primary source URL alongside each bundled direct-provider price
  snapshot entry.

### Changed

- Apply pricing freshness consistently to live-catalog and OpenRouter-routed
  prices, and to user overrides when `require_current_pricing` is enabled.
- Refresh the reviewed price snapshot, including correcting GPT-5.6 Luna from
  $1.00/$6.00 to $0.20/$1.20 and GPT-5.6 Terra from $2.50/$15.00 to
  $2.00/$12.00 per million input/output tokens.
- Exclude mock fixtures from billable-price summary counts.

### Fixed

- Keep duplicate configured model rows independent in `pricing-refresh`.
- Exempt deterministic `mock` fixtures from the paid-pricing gate while
  retaining them in coverage evidence.
- Refresh previously written direct-provider snapshot metadata when an upgraded
  package supplies a newer official snapshot.

## 2.5.0 - 2026-08-10

### Added

- Add `json_set` validation for unordered JSON arrays with duplicate rejection.
- Add `first_fenced_block` and `first_json_value` consumer policies for
  applications that intentionally select the first matching JSON payload.

### Changed

- Reject JSON Schema configurations with a missing or unsupported `type`, and
  ensure JSON booleans do not satisfy number or integer constraints.
- Warn when an Anthropic model is run with the `json` or `structured` preset:
  Anthropic does not receive an equivalent native JSON-mode request, so results
  are not directly comparable to providers that do.

## 2.4.3 - 2026-08-10

### Fixed

- Make the local MCP server interoperable with standard `initialize` clients,
  allowing Codex, Claude Code, and Cursor to discover and use the preflight
  tools.
- Resolve model aliases and provider presets for MCP configurations just as the
  CLI does, preventing valid preset configurations from terminating the MCP
  session.
- Support MCP `ping` requests.
- Do not load `.env.production` for mock or unconfirmed runs; credentials are
  loaded only for an explicitly confirmed live run.
- Return a standard-client `isError` result that names `confirm_paid_run` as
  the remedy when a live run lacks explicit confirmation.

### Changed

- Document copy-paste MCP setup for Codex, Claude Code, and Cursor, including
  the explicit approval boundary for paid preflight runs.

## 2.4.2 - 2026-08-02

### Fixed

- Restore compatibility with the repository's pinned CI Ruff release.

## 2.4.1 - 2026-08-02

### Fixed

- Preserve the recorded price ledger, including cached-input and tier pricing,
  when replaying a saved result.
- Add coverage that proves budget planning and result costing share the same
  resolved tiered/cached price evidence.

## 2.4.0 - 2026-08-02

### Added

- Add a local modern stdio MCP server with validate, dry-run, explicit-run, and
  baseline-diff tools.
- Add explicit OpenRouter live-catalog price refresh with user-override safety.

## 2.3.0 - 2026-08-02

### Added

- Add `llm-preflight init` with a no-key mock default and conservative explicit
  provider starter configurations that never write a secret.
- Add a fork-safe GitHub Actions preflight workflow example that pins its
  dependencies, uploads redacted evidence, and supports an optional baseline.

### Changed

- `init` is intentionally non-interactive in 2.3.0: it provides a deterministic
  mock default and explicit provider flags. Guided provider setup is deferred to
  a later release.

## 2.2.0 - 2026-08-01

### Added

- Add declared JSON consumer profiles (`raw_json`, `fenced_ok`, and
  `prose_tolerant`) and report contract-only failures when a stricter benchmark
  validator rejects a response accepted by the declared consumer.
- Add deterministic `golden` answer validation with per-profile accuracy and
  expected-versus-observed confusion counts.
- Add local-only `--audit-source PATH` for advisory literal model-ID and
  bundled-pricing findings with file and line evidence; it never imports
  application code or contacts providers.
- Add `priced_cost_usd`, `cost_confidence`, and `unpriced_models` while
  retaining the v1 all-or-null `total_estimated_cost_usd` contract.

### Fixed

- Fail a benchmark when its declared consumer parser rejects a response, and
  surface consumer rejections in terminal and Markdown contract diagnostics.
- Treat deeply nested JSON as invalid output rather than crashing a run.
- Emit the JSON result and embedded baseline comparison before `--baseline --ci
  --json` exits for a regression.

### Changed

- Clarify the product mission, vision, niche, and safe default validation
  workflow for coding agents.

## 2.1.1 - 2026-07-21

### Fixed

- Count Gemini thinking tokens as billable output tokens and apply cache-hit and
  long-context pricing tiers per request, including Gemini 3.1 Pro Preview's
  published 200k-input boundary.
- Keep `--json --baseline` machine-readable by embedding the comparison in the
  single JSON result document.
- Apply the same safe 256-token default output cap across provider clients.
- Fail comparison and recommendation gates for removed models, missing
  validation evidence, or zero-sample model results; deduplicate repeated test
  selectors before requests are planned.
- Refuse provider and catalog redirects, reject ambiguous unprefixed
  non-OpenAI quick-model IDs, load replay credentials from the recorded source
  config location, and preserve provider catalog order when dates are absent.

## 2.1.0 - 2026-07-21

### Added

- Add composable custom validation rules for JSON object or array shape, exact
  JSON array count, controlled values, numeric-only answers, maximum response
  length, and plain-text responses without Markdown formatting.
- Add curated, task-focused smoke packs for strict JSON extraction, support
  classification, code-patch summaries, source-grounded quizzes, and privacy
  boundaries. `agent-smoke` now selects this safe functional suite and excludes
  the opt-in concurrency load profile.

### Changed

- Document how to combine response contracts and how their parsing and
  comparison boundaries work.

## 2.0.5 - 2026-07-21

### Fixed

- Let `json_schema` contracts explicitly accept one Markdown-fenced JSON block
  when that matches the deployed consumer, while retaining raw JSON as the
  default and rejecting ambiguous multiple blocks or unfenced prose objects.
- Preserve the structured-response parsing policy in result samples and failure
  artifacts so a failed response can be interpreted against its real contract.

### Changed

- Document parser-aligned JSON contracts and include a deterministic
  fence-tolerant mock example.

## 2.0.4 - 2026-07-17

### Added

- Add `--version` to the main command.

## 2.0.3 - 2026-07-17

### Fixed

- Report `output_tokens_per_second` as unavailable when a provider delivers
  the response as a terminal burst rather than an incremental stream (fewer
  than two text chunks, or a generation window under 100 ms). Previously a
  buffered response — observed with Gemini — inflated throughput by orders of
  magnitude because the post-TTFT window measured transport, not generation.

### Changed

- README: add real cross-provider run output, a "How it compares" section,
  precise wording for the no-third-party-dependencies claim and deterministic
  validation, and absolute documentation links so the PyPI project page and
  sdist README no longer point at files excluded from the distribution.
- Remove the unused `_request_count` helper superseded by `estimate_budget`.
- Raise test coverage from 81% to 86% (316 tests) with new error-branch and
  validation tests across the runner, profiles, features, capability ledger,
  and environment modules.
- Mark the distribution as Beta (`Development Status :: 4 - Beta`).

## 2.0.2 - 2026-07-16

LLM Preflight is a local, cross-provider preflight CLI for validating a model
switch before it reaches production. It runs deterministic prompt validation
alongside latency, tokens, and cost across OpenAI, Anthropic, Gemini, xAI,
OpenRouter, and OpenAI-compatible providers.

The project now ships as a single package and command: `llm_preflight` /
`llm-preflight`. All compatibility surfaces from the earlier `llm-speed-bench`
/ `llm_bench` naming — the `llm-bench` command alias, the `llm_bench` import
namespace, and the legacy PyPI compatibility shim — have been removed.

## 2.0.1 - 2026-07-16

### Fixed

- Add the public `python3 -m llm_preflight` entry point for source checkouts
  and generated guidance; retain `python3 -m llm_bench.cli` as a legacy import
  path only.

## 2.0.0 - 2026-07-16

### Changed

- Rename the project and primary PyPI distribution to **LLM Preflight**
  (`llm-preflight`): a local, cross-provider preflight for a model switch.
- Make `llm-preflight` the primary command while retaining `llm-bench` and the
  `llm_bench` Python import namespace as supported compatibility interfaces.
- Update public documentation, examples, package artifacts, and release
  automation to use the new product name and primary command.

## 1.2.2 - 2026-07-16

### Fixed

- Keep plain-prompt validation results in model summaries, quality gates, and
  recommendation ranking so an invalid output can never pass or be recommended.
- Reject unknown validation keys and support explicit exact-match validation in
  ordinary and starter configurations.
- Calculate request and retry-expanded cost limits from every profile case,
  warmup, prompt override, and output limit.
- Preserve per-model results when client setup, runtime URL validation, or a
  request worker fails instead of aborting the benchmark.
- Keep transient catalogue probe failures retryable; only structured stable
  incompatibility evidence changes a model's catalogue classification.
- Measure successful request latency and time-to-first-token per final attempt,
  excluding retry backoff, and apply the same retry policy to Responses API
  requests.
- Gate CI comparisons on configured cost regressions, reject ambiguous custom
  prompt names and empty `contains` rules, and make numeric-only checks reject
  explanatory or contradictory output.
- Keep interactive catalogue comparisons head-to-head with selected approved
  models; require a distinct paid-run confirmation even after a stray `y` at
  the stop-mode prompt; preserve discovery deltas when a candidate run fails.
- Prefer authoritative ready-text catalogue evidence over model-name heuristics
  and redact Gemini and xAI key formats from all terminal, JSON, candidate-plan,
  and result output.
- Preserve transport retries by classifying socket failures by exception type;
  bootstrap a catalogue snapshot only after a successful first candidate run.
- Gate CI comparisons on validation-rate regressions as well as latency,
  request success, and cost; reject legacy built-in test aliases as custom
  prompt names.
- Keep `all` in catalogue review to the four inexpensive functional checks,
  protect invalid-scheme URL errors from credential echoes, and harden local
  workspace, exact-model-selection, approval-file, and query-encoding edges.

## 1.2.1 - 2026-07-16

### Fixed

- Keep the credential-free `.env.production` template created by `catalog init`
  identical to the checked-in `.env.example` template.

## 1.2.0 - 2026-07-16

### Added

- Add the local model lifecycle: `catalog init`, `catalog refresh`, and
  `catalog prepare`, followed by the normal interactive benchmark flow and
  explicit `models approve` promotion.
- Add local catalogue snapshots and model-change diffs; retain `watch-new` and
  `approve-model` as compatibility aliases.
- Add interactive `--approve-to` promotion, explicit retry-risk acceptance,
  and candidate-plan `--replace` protection.
- Classify catalogue entries as ready text benchmarks, text candidates needing
  one explicit probe, or incompatible generic-text endpoints using provider and
  OpenRouter capability evidence.
- Add `catalog probe` and a local, permission-restricted capability ledger that
  records only safe compatibility evidence, never response text or credentials.
- Add `--migration-check`: a one-repetition, no-warmup three-case response and
  basic-contract preflight for comparing a candidate model with an incumbent.
- Add a custom-contract tutorial and runnable mock examples for JSON extraction,
  exact intent routing, and required-content validation.
- Rename default test packs around their user value: quick migration, exact
  routing, structured output, numeric instruction, and concurrency health.
  Keep the former selectors as compatibility aliases.

### Fixed

- Refuse a concurrent benchmark targeting the same results directory before it
  can issue duplicate paid requests.
- Migrate legacy catalogue snapshots without reporting every model as changed
  solely because richer capability metadata was introduced.

## 1.0.3 - 2026-07-13

### Changed

- Keep internal agent, roadmap, launch, and release-runbook material out of
  public source distributions.
- Restrict source artifacts to runtime code, package metadata, user-facing
  documentation, and example configuration files.

## 1.0.2 - 2026-07-13

### Added

- Add `llm-bench --init` to create a safe, deterministic no-key mock benchmark
  without overwriting an existing configuration.
- Visually separate interactive setup stages and final terminal results,
  quality-gate, and decision sections.
- Render `--dry-run` as a readable terminal plan by default; retain JSON output
  with `--json` for automation.
- State the qualified recommendation explicitly and show the interactive
  command after `--init` creates a mock configuration.

### Fixed

- Exclude models that fail any selected test from fastest, cheapest, and
  best-value recommendations; list them with their failed test instead.
- Correct smoke-mode documentation: it reduces repetitions and warmups, but
  does not suppress selected profile-case or load-test expansion.

## 1.0.1 - 2026-07-13

### Fixed

- Handle Ctrl-C cleanly with exit code `130` and without writing artifacts.

## 1.0.0 - 2026-07-13

### Added

- Cross-provider smoke testing, discovery, deterministic validators, reports,
  pricing checks, retry diagnostics, and CI-oriented controls.
- A mock-provider quickstart and `--no-save` for no-key and CI workflows.
- Retry jitter plus nominal and retry-expanded request/cost planning.

### Security

- Redact all custom request-header values from result artifacts and output.
- Enforce configured cost ceilings only when complete pricing is available.

### Fixed

- Apply CLI `--tests` selections to budget enforcement.
- Keep the static type-check security gate green.
