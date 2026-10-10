# Changelog

All notable changes to this project are documented here.

## 2.20.0 - 2026-10-10

### Added

- Bundled model retirement snapshot of the official Anthropic and OpenAI
  deprecation pages (`llm_preflight/retirements.py`) with a three-state
  verdict: retired fails, retiring or a stale row is inconclusive, unknown
  stays unknown. Replacements are provider-stated only.
- `--audit-source` attaches a `retirement` verdict to every reference, adds
  `decision` and ready `--quick --dry-run` `next_commands`, prints a `Next:`
  block, and exits 1 or 3 under `--ci`.
- `--doctor` fails a retired model and warns on a retiring or stale one;
  `--dry-run` lists retirement verdicts after eligibility. Under `--ci` both
  exit 1 for a retired model and 3 for a retiring or stale one.
- Guide: `docs/guides/retirements.md`, including the release retirement
  review.

### Changed

- Doctor output prints `warning:` instead of `ok:` for warning-severity
  checks, including pricing warnings.
- `--audit-source` confidence is `limited_static_pricing_and_retirement`.
- `--doctor` now fails, without `--ci`, a configuration that approves a model
  whose retirement date has passed; this includes the bundled Action's doctor
  step once pins move to this version. Many OpenAI rows in the bundled
  snapshot retire on 2026-10-23.
- Snapshot rows go stale 30 days after their review date (`as_of`, 2026-10-09
  in this release); from then `--ci` returns 3 for every model in the snapshot
  until the package is updated. Models with no row are unaffected.
- Scans whose references are all outside the snapshot report `decision: none`,
  not pass.
- Point the repository Action default, mock smoke workflow and CI examples at
  the published 2.19.2 package. The `v2.19.2` tag retains its 2.19.1 default;
  set `package-version` explicitly when using that tag.

## 2.19.2 - 2026-10-10

### Fixed

- Evaluate per-prompt `validation_fixtures` in `--contract-check`, in the
  pre-run fixture guard and in change-plan recommendations. Previously only
  top-level fixtures were checked, so a multi-prompt configuration's fixtures
  were never proven.
- Reject `validation_fixtures` that have no `validation` at the same level
  instead of checking them against the implicit non-empty rule.
- Scope `--prompt` to the selected prompt's own fixtures: a prompt with its own
  `validation` no longer inherits top-level `validation_fixtures`, which were
  checked against the wrong validator.

### Added

- Dry-run plans list each non-eligible model with its reason and next step,
  and state that eligibility gates `catalog prepare`, does not block a
  reviewed bounded run of text models, and that a live run refuses the models
  it lists as refused.
- Accepted and rejected fixtures in the bundled custom-contract examples.
- `--contract-check` reports prompts that declare a `validation` but no
  fixtures (`unproven_prompts`) and prints a note for each.

### Changed

- The README leads with the mission, the no-key demo and one failing
  contract; release notes live in this changelog.
- The configuration reference documents contract fixtures at both levels.
- Point the repository Action default, mock smoke workflow and CI examples at
  the published 2.19.1 package. The `v2.19.1` tag retains its 2.19.0 default;
  set `package-version` explicitly when using that tag.

## 2.19.1 - 2026-10-08

### Added

- Bundle Claude Haiku 5.5's reviewed input, output and cache-read pricing,
  including the higher full-request band above 100,000 total input tokens.
- Add bounded Anthropic 5.5 configurations for the original comparison cases,
  full built-in checks and a separate agent smoke.

### Fixed

- Omit unsupported `temperature` from native Claude Haiku 5.5 requests.
- Apply Claude Sonnet 5.5's October 7 cache-read price cut to $0.10 per
  million tokens, including configurations with persisted official snapshots.
- Normalize Anthropic input usage to include cache reads and writes, and
  retain reported cache-write usage. Writes without an explicit reviewed
  write rate make cost unavailable rather than silently understating it.

### Changed

- Update the README, documentation homepage and 27-model comparison with
  October 7 Haiku 5.5 and Sonnet 5.5 measurements, including the retained
  Haiku smoke failure and the separate request and cost totals.
- Point the repository Action default, smoke workflow, and CI examples at the
  published 2.19.0 package after the release.

## 2.19.0 - 2026-09-30

### Added

- Add native Z.ai GLM-5.3 chat with reviewed input/cache/output pricing,
  deterministic streaming and invalid-reasoning fixtures, source detection,
  OpenRouter discovery, and a bounded eight-case comparison example.
- List GLM-5.3 on the homepage and comparison table, and
  include it in maintained frontier and comparison examples.
- Include GPT-6.1 Sol in the OpenAI frontier candidate example and bundled
  official pricing snapshots, including its discounted cache and long-context
  rates.
- List GPT-6.1 Sol on the homepage and comparison table, and provide a
  bounded example of the eight-case study.
- Include GPT-6.1 Sol in automatic discovery and maintained comparison
  examples, with deterministic provider and pricing-boundary tests.

### Fixed

- Omit unsupported `temperature` from GPT-6.1 Sol requests.
- Preserve OpenAI's reported cache-write usage, price GPT-6.1 Sol's writes
  separately from reads, and include the write premium in its cost plan.
- Use current bundled prices in the flagship example instead of a stale
  Anthropic price override.
- Apply GPT-5.5's official cached-input rates and full-request price band
  above 272,000 input tokens, correcting long-context underestimates.
- Start Grok's long-context price band at 200,000 input tokens, matching
  the official inclusive threshold.

### Changed

- Add dated live comparison results: GPT-6.1 Sol passed 16/16 cases;
  GLM-5.3 through OpenRouter / Relace passed 14/16. Document the two
  validation failures, measured routes, latency, usage and estimated costs.

## 2.18.2 - 2026-09-28

### Fixed

- Bundle Claude Sonnet 5.5 and Haiku 4.5's official direct-provider prices so
  strict cost checks and estimates work for newly configured routes.
- Omit `temperature` from Claude Sonnet 5.5 requests because its API rejects
  nondefault sampling values.

### Added

- Include Claude Sonnet 5.5 in the priced frontier candidate example.

### Changed

- Point the repository Action default, smoke workflow, and CI examples at the
  published 2.18.1 package while preparing 2.18.2.
- Point the repository Action default, smoke workflow, and CI examples at the
  published 2.18.2 package after the release.

## 2.18.1 - 2026-09-28

### Fixed

- Preserve official native adapter and text-readiness metadata when enriching
  provider catalogue entries with OpenRouter capabilities.
- Pass configured system prompts to OpenAI Responses requests so contract
  checks exercise the intended instructions.

### Added

- Document a dated, scoped model comparison and list its measured models on
  the homepage without implying general model approval.

### Changed

- Point the repository Action default, smoke workflow, and CI starter at the
  published 2.18.0 package after the release.

## 2.18.0 - 2026-09-28

### Fixed

- Compare output-schema enum members recursively by JSON value type so numeric
  `1`/`0` cannot impersonate boolean `true`/`false` inside objects or arrays.
  Preserve numerical equivalence.
- Reject non-JSON `NaN` and `Infinity` constants and finite-range overflow in
  all structured-output parsing policies, including fields with no numeric
  schema rule. Reject decimal values that would round into a different number,
  and treat oversized integers as invalid output instead of raising a decoder
  exception. Prose parsing does not salvage nested values from a malformed
  outer value. Bind these corrections to validator semantics
  `output-schema-3` so earlier evidence is not treated as equivalent.
- Preserve missing or invalid provider usage as unavailable cost evidence;
  retain known subtotals and distinguish missing usage from missing prices.
  Include warmups when deciding completeness and reporting run cost.
- Apply strict pricing freshness to every billable source description and
  reject future review dates under the strict policy.
- Reject unsupported output-schema keywords and invalid rule combinations
  recursively before planning or provider requests; retain the separate
  canonical tool-schema subset.
- Preserve omitted Gemini output usage and avoid coercing malformed token
  counts into a valid estimate.
- Flag unverified cost completeness in legacy artifacts and suppress cost
  deltas or recommendations based on incomplete evidence. Retain known final
  response cost after retries while keeping unobserved retry usage unknown.

### Added

- Enforce boolean `additionalProperties` on output objects and inclusive finite
  `minimum`/`maximum` bounds on numeric outputs, including nested array items.
  Reject invalid rule combinations and non-finite numeric responses.
- Bind output-validator semantics to contract provenance. Different known
  semantics are incompatible; matching contract hashes without a semantics
  version have unknown comparability.
- Add a source-checkout application-owned configuration example with reviewed
  request/schema/config fixtures and tests for consumer drift. It does not
  execute application code through Preflight or establish pilot adoption.

### Changed

- Point the repository Action default, smoke check, and starter workflow at
  the published 2.17.1 package during release preparation.
- Recheck all 34 bundled public price snapshots on 2026-09-28 and link OpenAI
  rows to their model-specific official pricing pages. Qwen rows retain
  conservative USD list rates while a temporary discount is displayed.
- Refresh the synthetic report gallery with explicit invented cost/usage
  coverage so its intended decisions remain reproducible.

## 2.17.1 - 2026-09-25

### Added

- Add a project integration guide with an application contract, local fixtures,
  existing env-file reuse, report export, and a no-spend CI path.

### Changed

- Point the Marketplace Action default and no-spend CI examples at the
  published 2.17.0 package.
- Make MCP onboarding guidance explicit in its guide and safe-workflow resource.

## 2.17.0 - 2026-09-24

### Added

- Render saved schema-version-1 results as self-contained offline HTML or a
  compact, privacy-filtered GitHub Markdown job summary; unknown major schemas
  are rejected.
- Add synthetic report examples for a schema regression, a cheaper candidate
  that fails its contract, and a latency/cost baseline regression.
- Add no-spend and opt-in paid-run summaries to the Marketplace Action.
- Add the pre-merge report story and reproducible gallery to the README.

### Changed

- Update the GitHub Marketplace Action's default package version to the
  publicly available 2.16.0 release.
- Pass the Action's package-version input through the step environment instead
  of interpolating it into the shell script.
- Retry the Marketplace Action package install so a pin made just after
  publish is not failed by PyPI index lag.
- Document native routes, official pricing snapshots, and remaining gaps
  (Gemini 4, Kimi/GLM native, Jev) for package 2.16.0.

## 2.16.0 - 2026-09-22

### Added

- Add official pricing snapshots for GPT-6 Sol, GPT-6 Luna, Claude Opus 5.5,
  and Grok 4.7.

### Changed

- Point the frontier candidate example at the current GPT-6, Claude, and Grok
  flagship IDs. Gemini 4 still has no public API model ID or price table, so
  the Gemini rows stay on 3.1 Pro, 3.8 Flash, and 3.1 Flash-Lite. DeepSeek
  V4.1 Flash / V4 Pro and Qwen 3.8 remain the first-party Chinese routes we
  snapshot; Kimi and GLM stay OpenRouter or `openai_compatible` until a
  first-party adapter exists.

## 2.15.1 - 2026-09-20

### Changed

- Update the GitHub Marketplace Action's default package version to the
  publicly available 2.15.0 release.
- Refuse typed-decision and other non-text catalogue types on the text smoke
  path before any provider request, including OpenRouter `jev-*` rows.
- Enforce the CLI request and cost caps on MCP `run_preflight` live runs.
- Keep native `text-candidate` rows on the probe path when OpenRouter metadata
  claims they are text-ready.
- Count CJK characters as whole tokens in the pre-run cost cap so the spend
  gate does not under-count Qwen and other CJK prompts.

## 2.15.0 - 2026-09-20

### Added

- Add official pricing snapshots for GPT-6 Astra, Claude Fable 5.1, Gemini 3.8
  Flash, DeepSeek V4.1 Flash (`deepseek-flash`) and V4 Pro, Qwen 3.8 Max,
  Qwen 3.8 Flash, Qwen 3.7 Plus, and TypeSafe Jev.
- Add native `deepseek` and `qwen` catalogue/chat routes, and a `typesafe`
  catalogue route for Jev. Jev stays visible as a typed-decision model and is
  not eligible for the generic text smoke adapter. OpenRouter metadata cannot
  reclassify an official non-text catalogue type into a text smoke candidate.

### Changed

- Point the frontier candidate example at current public flagships: three
  models each from OpenAI, Anthropic, Gemini, xAI, and Qwen, plus DeepSeek's
  two live API IDs. Gemini 4 has no public API model ID or price table, so it
  is omitted.
- Default the native `qwen` route to the international DashScope
  compatible-mode endpoint so discovery and USD snapshots share one region.

## 2.14.0 - 2026-09-09

### Added

- Reuse an explicitly selected project env file from a benchmark configuration
  or provider starter. Shell values retain precedence; doctor reports only the
  credential source, never a credential value.

## 2.13.0 - 2026-09-08

### Added

- Add local image-input preflight support for image-to-text contracts on
  OpenRouter/OpenAI-compatible chat routes and Gemini. Inputs are constrained
  to verified local image fixtures; results retain metadata and a content hash,
  not image bytes.

## 2.12.0 - 2026-09-08

### Added

- Add no-spend `--contract-check` validation fixtures. A configured contract
  must prove both an accepted and a rejected response before its fixtures pass.
- Add strict, canonical tool-definition linting for name, description, and a
  portable JSON Schema parameter subset. It validates definitions but does not
  invoke tools or make provider requests.
- Add secret-safe result provenance: configuration, contract, resolved-route,
  pricing, and combined evidence fingerprints, prompt hashes, and declared
  request/cost caps.
- Add `--change-plan REF`, a Git-aware local report of changed, staged, and
  untracked files with literal model and contract-surface signals plus safe
  next commands. It never loads credentials, calls a provider, or authorizes
  paid work.
- Add expiring local dry-run approval receipts. They bind a human review note
  to a plan hash and its request/cost bounds, but are deliberately never
  accepted as paid-run authorization.

### Fixed

- Reject baseline comparisons with changed output-contract evidence or duplicate
  model names, and label legacy results without provenance as `unknown`.
- Include deleted files in Git-aware change-plan evidence and preserve existing
  parent-directory permissions when writing approval receipts.
- Give `catalog probe` the same explicit environment-file controls as benchmark
  commands.

### Changed

- Publish package classifiers and project URLs in wheel metadata, and clarify
  the README and north star around catching integration regressions.

## 2.10.0 - 2026-08-31

### Added

- Add standard MCP tool safety annotations, honest structured-output schemas,
  and a discoverable no-spend workflow resource for coding agents.
- Add a registry-ready `server.json` for the local PyPI stdio package, with a
  required `--workspace` filepath argument, plus a repository plugin skill that
  teaches the same no-spend workflow without adding a workspace command.
- Add TestPyPI clean-install coverage that starts the MCP server and reads its
  safe-workflow resource without credentials or provider traffic.

### Fixed

- Resolve the default config-adjacent `.env.production` through the same
  workspace-containment check as explicit paths, including symlink targets.
- Preserve an explicit `env_file` in the elicitation retry state so an
  approved paid-run retry uses the environment file the user selected.

## 2.9.0 - 2026-08-31

### Added

- Add a no-spend-by-default GitHub Marketplace Action: doctor, pricing, and
  bounded dry-run checks run automatically; a paid smoke requires an explicit
  action input and caller-provided credentials.
- Add safe provider-breakage and pricing-drift issue forms, plus a concise
  comparison page that keeps local contract preflight distinct from evaluation,
  observability, and provider administration.

### Changed

- Align GitHub repository metadata and README discovery with the local
  integration-change preflight niche: safe first run, workflow choices,
  explicit spend boundary, and a link to complete release history.

## 2.8.0 - 2026-08-31

### Added

- Add deterministic smoke-eligibility evidence that distinguishes eligible
  routes from models needing a probe, adapter evidence, compatible modality,
  current pricing, or bounded limits.
- Make `catalog prepare` retain only smoke-eligible models in its runnable
  candidate configuration, while keeping excluded models and their reasons in
  catalog refresh evidence.

## 2.7.5 - 2026-08-31

### Fixed

- Replace stale standard GPT-5.6 Luna, Terra, and Sol input/output rates from
  their primary source.
- Represent GPT-5.6 cached-input and long-context pricing, plus Grok 4.3
  cached-input and long-context pricing, in the shared pricing ledger.
- Remove the retired, unpriced `openrouter:minimax/minimax-m3` route and
  unpriced Gemini model from the tracked cross-provider examples.

### Changed

- Add a tracked frontier-candidate plan for current OpenAI, Anthropic, Gemini,
  and xAI models, including Grok 4.5 and Grok 4.6; keep it separate from the
  approved release smoke until compatibility evidence is retained.
- Assert every bundled pricing entry's reviewed rate, provider model ID,
  source URL, and review date in deterministic tests. The release review still
  verifies official provider documentation; the unit suite never fetches it.
- Add a tracked, fully priced approved smoke cohort and require its review
  before an owner-authorized paid release smoke.
- Align the README, package description, north star, product decisions, and
  pricing guide around the local contract-preflight scope.

## 2.7.4 - 2026-08-20

### Fixed

- Separate the human terminal decision state and blocking warnings from the
  executive ranking, so automation is directed to JSON or MCP evidence.

### Changed

- Clarify paid-run pricing enforcement, agent no-spend sequences, test-pack
  coverage, and the current GitHub Actions starter version in public docs.
- Derive legacy installer metadata from the package version and ship the PEP
  561 `py.typed` marker for typed consumers.

## 2.7.3 - 2026-08-20

### Fixed

- Require complete pricing across every configured tier before allowing a
  current-pricing gate to authorize a paid benchmark.
- Make unknown decision states fail closed and document exit code 3 for
  inconclusive evidence in the coding-agent guide.

## 2.7.2 - 2026-08-20

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
