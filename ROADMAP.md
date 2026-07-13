# Roadmap

## Positioning

LLM Speed Bench is a local CLI for smoke-testing live LLM models before they
hit production.

It is built for engineers who need to quickly answer:

- Does this model pass my actual prompt/test?
- How fast is it from my environment?
- How much does it cost for my workload?
- What provider-specific quirks will break production?
- Is a cheaper or newer model safe enough to try?

This project should stay narrow. It should not try to become a full app eval
platform, hosted observability system, RAG framework, red-team suite, or public
leaderboard. Those spaces already have strong tools. The defensible niche is
fast, local, cross-provider model validation.

## Product Principles

- **Fast first run:** a useful smoke test should be possible in minutes.
- **Local by default:** configs, prompts, results, and failed outputs stay on
  the user's machine unless they choose otherwise.
- **Provider quirks handled:** users should not need to memorize every
  provider's JSON, reasoning, streaming, or token-accounting behavior.
- **Custom prompts are first-class tests:** built-in tests and user tests
  should mix naturally.
- **Cost is part of correctness:** failed-but-billable calls must be visible.
- **Interactive and scriptable:** the same workflows should work in a polished
  terminal UI and in CI.

## Current State

### Shipped Foundation

- Custom prompts can run as first-class tests beside built-in profiles.
- Interactive mode clears the screen at start, colorizes sections, and separates
  model, test, and repetition selection.
- `--tests` is available as the user-facing alias for `--profiles`.
- Interactive confirmation shows estimated paid requests and cost when pricing
  is configured.
- Terminal and Markdown reports include a pass/fail dashboard.
- Provider presets expand `json`, `no-reasoning`, `low-latency`, and
  `structured` into provider-specific request options without overriding
  explicit user settings.
- Result summaries include diagnosis hints for common failure patterns.
- The dependency-free JSON Schema subset supports required keys, nested object
  paths, arrays, `minItems`, `maxItems`, `enum`, and primitive types.
- `source-to-quiz` in checked-in example configs uses prompt-level
  `"presets": ["structured"]`.
- The built-in `structured-extraction` profile uses `"presets": ["structured"]`.
- `--catalog`, `--doctor`, `--smoke`, `--quick`, `--diff`, `--baseline --ci`,
  `--matrix`, `--replay`, `--changed-since`, model aliases, and environment
  overlays exist as fast testing workflows.
- Saved artifacts include JSON, full Markdown, and executive-summary Markdown.
- Interactive and smoke runs default to failure-only response retention unless
  explicitly configured otherwise.
- `--dry-run` prints the resolved run plan without generation requests.
- `--stop-on api-error|test-fail|any-fail` separates provider/request errors
  from model-output failures.
- `--fail-fast` remains as a compatibility alias for `--stop-on any-fail`.
- Exit semantics treat invalid test output as failure, not only transport
  errors.
- Central secret redaction is applied to catalog output, dry-run request output,
  run results, saved JSON artifacts, Markdown reports, source config snapshots,
  and common provider error strings.
- `.env.production` loading can be disabled with `--no-env-file` or replaced
  with an explicit `--env-file PATH`.
- Saved result artifacts are checked by tests to ensure known fake secrets do
  not leak into JSON or Markdown outputs.
- Retryable transport/provider failures are classified and retried once by
  default, with configurable attempts and backoff through `request.retry`.
- Retry delays include bounded jitter, and plans distinguish nominal work from
  the retry-expanded request and cost upper bound.
- Result summaries include retry counts, retry reasons, and failure categories.
- Shell-level CLI tests cover exit codes, stop modes, and budget enforcement.
- `--no-save` supports CI checks that only need stdout and exit status.
- `--pricing-check`, `--dry-run`, and `--doctor` surface unknown or stale
  pricing warnings before live generation requests.
- Explicit user pricing overrides are marked in `pricing_metadata`; public
  registry prices retain their `as_of` date.

## Next Steps

These are the next product slices to implement in order. The order matters:
trustworthy live results and trustworthy cost data come before richer reporting.
Each slice should land with focused TDD tests and deterministic provider
fixtures.

## MoSCoW Priorities

This priority layer governs the detailed backlog below. A feature moves only
when it preserves the product's narrow promise: trustworthy local model
preflight, not a general evaluation platform.

### Must Have

- **Pricing refresh and cost integrity:** refreshable prices, one shared price
  source for budgets and results, and explicit cost-confidence levels.
- **Retry and load-aware failure integrity:** make retries, throttling, and
  their latency impact visible rather than misclassifying them as model quality
  failures.
- **Unambiguous run safety:** keep request counts, retry-expanded cost bounds,
  stop modes, and response-retention behavior clear before paid requests run.
- **Secure, reproducible releases:** retain the verified TestPyPI gate and
  GitHub Trusted Publishing workflow.

### Should Have

- **Interactive visual upgrades (current):** clearly separated sections,
  readable milestones, and a stronger final-results view. These improve daily
  use and first impressions, while safety and measurement semantics remain
  unchanged.
- **Production-real smoke packs and common validators:** recommended safe
  preset, curated prompt packs, and deterministic validation primitives.
- **First-run configuration UX:** `llm-bench init`, guided provider setup, and
  stronger provider-specific `doctor` guidance.
- **Catalog watch workflow:** snapshot, diff, and test only newly discovered
  models; this is the primary differentiated workflow.
- **Launch assets and focused OSS outreach:** terminal demo, result screenshot,
  README topics, and the prepared technical posts.

### Could Have

- **Baseline regression comparisons:** threshold-based quality, latency, and
  cost changes against a saved run.
- **CI enhancements:** annotations, compact PR summaries, and templates beyond
  the current exit-code and budget-enforcement behavior.
- **HTML and expanded report artifacts:** model-by-test matrix, redacted failed
  examples, and recommendation summaries after cost data is trustworthy.
- Additional provider presets and advanced validators.

### Won't Have Yet

- Hosted observability, telemetry collection, shared dashboards, or a public
  leaderboard.
- Full RAG evaluation, broad red-teaming, large academic benchmark suites, or
  a general LLM evaluation platform.

### Recommended Release Order

1. **1.0.2:** interactive visual upgrades, with output regression tests.
2. **1.0.3:** pricing refresh and cost-integrity guarantees.
3. **1.1.0:** production smoke packs, common validators, and first-run setup.
4. **1.2.0:** catalog snapshots, diff, and `watch-new`.
5. **Later:** baselines, CI annotations, and HTML reporting.

### 1. Run Plan, Cost, and Failure Semantics

This is the next priority because users must understand what will happen before
the CLI spends money.

- Add a human-readable non-JSON `--dry-run` rendering for terminal use.
- In interactive mode, make the run plan impossible to miss:
  - selected models
  - selected tests
  - repetitions
  - warmups
  - paid request count
  - estimated cost when pricing exists
  - response retention mode
  - stop mode
  - load/concurrency expansion
- Keep `load` clearly marked as a concurrency test, not a normal prompt test.
- Consider making interactive `all` select a recommended smoke set first and
  require explicit confirmation for `load`.
- Keep failure language consistent everywhere:
  - `API FAIL`: request, credential, provider, network, rate-limit, or
    unsupported-parameter problem
  - `API OK / TEST FAIL`: the model responded but did not satisfy the validator

### 2. Retry Hardening and Load-Aware Failure Classification

This is table-stakes for live API smoke testing. A single provider-side 429 or
network blip should not silently corrupt p95 latency, flip a model to FAIL, or
make a model migration look worse than it is.

The first retry/classification slice is shipped. Remaining work:

- Add shell-level output tests for retry summaries in terminal progress and
  Markdown reports.
- Make load tests stricter:
  - label rate-limit-heavy load runs clearly
  - separate steady-state quality failures from load-induced throttling
  - do not let retry sleeps inflate normal p95 without being obvious

### 3. Pricing Refresh and Cost Integrity

Cost is a headline feature. Wrong pricing data silently corrupts the product's
core promise more than an ugly report does.

The first pricing freshness slice is shipped. Remaining work before HTML
reports:

- Add a pricing refresh workflow:

  ```bash
  llm-bench pricing-check benchmark.auto.json
  llm-bench pricing-refresh benchmark.auto.json --write
  ```

- Compare public registry entries against live catalog prices when providers
  expose pricing, especially OpenRouter.
- Add tests proving budget estimates and result costs use the same price source.
- Add docs for cost confidence levels:
  - live catalog price
  - public registry price with `as_of`
  - explicit user override
  - unknown price

### 4. Production-Real Smoke Tests and Custom Prompts

The built-ins should feel like production failure modes. Custom prompts should
be the main value, not an advanced feature.

- Create a recommended smoke preset that avoids surprise load expansion:
  - `chat-fast`
  - `classification`
  - `structured-extraction`
  - `reasoning`
  - checked-in custom prompts such as `source-to-quiz`
- Keep `load` available, but opt-in and visually distinct.
- Add guided custom test creation:
  - prompt text or prompt file
  - expected exact match, regex, JSON field, JSON schema, numeric answer, or
    allowed values
  - optional provider presets such as `structured`
- Add common validators:
  - `json_object`
  - `json_array`
  - `no_markdown`
  - `exact_count`
  - `allowed_values`
  - `numeric_answer`
  - `max_chars`
- Add curated smoke packs:
  - strict JSON extraction
  - customer support classification
  - code patch summary
  - source-grounded quiz generation
  - refusal/safety boundary checks
- Make failure examples easy to inspect without saving every successful
  response.

### 5. First-Run Configuration UX

The tool should reach a useful first result in under five minutes.

- Add `llm-bench init`.
- Add guided provider setup.
- Add a mock-provider demo config that requires no paid API.
- Add a cheap live-provider starter config.
- Add config validation with provider-specific hints.
- Add `llm-bench doctor` improvements:
  - credential checks
  - catalog reachability
  - selected model availability
  - unsupported option warnings
  - capability hints for unsupported normalized fields such as `temperature`

### 6. Catalog Watch: The Killer Workflow

Make model discovery a first-class workflow:

```bash
llm-bench catalog benchmark.auto.json --save
llm-bench catalog-diff old.json new.json
llm-bench watch-new benchmark.auto.json --tests source-to-quiz
```

Use case:

> A provider publishes new models. Run only the newly discovered models against
> my smoke tests.

Implementation priorities:

- Store catalog snapshots with provider, model id, display name, created date
  when available, and pricing when available.
- Add `catalog-diff` output that separates added, removed, renamed, and changed
  models.
- Add `watch-new` to run only newly discovered models against selected smoke
  tests.
- Add docs for the model-switching workflow:

  ```bash
  llm-bench watch-new benchmark.auto.json \
    --tests source-to-quiz \
    --stop-on api-error \
    --dry-run
  ```

### 7. Reports and Output Artifacts

Reports come after safety, run clarity, retry classification, and pricing
freshness so that richer artifacts do not leak secrets or amplify misleading
results.

- Add a single-file HTML report with:
  - model summary table
  - pass/fail dashboard
  - model-by-test matrix
  - failure reasons and hints
  - failed output examples after redaction
  - cost and latency rankings
- Add `--report markdown|html|json|all`.
- Add a compact CI/PR Markdown summary artifact.
- Add a model recommendation summary:

  ```text
  Recommended: gpt-4.1-nano
  Reason: passes all tests, lowest measured cost, p95 under 4s.
  ```

- Add model-by-test matrix details:
  - pass/fail
  - latency
  - cost
  - failure reason

### 8. Baselines and Regression Testing

- Support `--baseline latest`.
- Add threshold syntax:

  ```bash
  llm-bench benchmark.json \
    --baseline latest \
    --fail-on success:-5%,p95:+30%,cost:+25%
  ```

- Add result comparison summaries:
  - pass/fail changes
  - latency deltas
  - cost deltas
  - token usage deltas
  - model rank changes
- Store and compare model-by-test regressions, not only model-level summaries.

### 9. CI Mode

- Make CI output compact and deterministic.
- Support GitHub Actions annotations.
- Add optional PR comment artifact.
- Add budget enforcement examples and CI templates:

  ```json
  {
    "max_requests": 50,
    "max_estimated_cost_usd": 3.0
  }
  ```

## Later Bets

### Provider Presets

Continue expanding provider-aware presets that map a simple intent to
provider-specific request options:

```json
{
  "presets": ["json", "no-reasoning"]
}
```

Initial presets:

- `json`: request JSON/object output where the provider supports it.
- `no-reasoning`: suppress public reasoning text when possible.
- `low-latency`: minimize output length and reasoning overhead.
- `structured`: combine JSON mode with strict validation-friendly defaults.

Examples:

- Gemini: `responseMimeType`, `thinkingConfig.includeThoughts`
- OpenRouter: `response_format`, `include_reasoning`, `reasoning`
- OpenAI-compatible APIs: compatible response format fields where supported
- Anthropic: provider-safe request shaping without leaking unsupported fields

### Advanced Validation

After the common validators are stable, consider deeper validation helpers that
still support the smoke-testing workflow:

- semantic similarity against a reference answer
- simple code compilation checks
- tool-call argument validation
- lightweight PII/safety boundary checks

### Failure Diagnosis

Continue converting common failure patterns into hints:

- Public reasoning leaked before answer
- Markdown fenced JSON
- Empty response with token usage
- Output stopped at max token limit
- Provider rejected unsupported parameter
- Missing token usage
- Rate limit / transient provider failure

Example:

```text
MiniMax M3 failed after using all 1200 output tokens with no content.
Hint: OpenRouter reasoning models may need no-reasoning and json presets.
```

### Optional Advanced Evaluation

Only add these if they support the core smoke-testing workflow:

- Custom Python validators
- Optional LLM-as-judge scoring
- Pairwise model comparison
- Human review export

## Product Differentiation

This project should win on:

- speed of setup
- cross-provider catalog discovery
- provider-specific API quirk handling
- real latency/cost measurement
- custom prompt smoke tests
- local-first results
- clear terminal UX

It should avoid trying to win on:

- full application tracing
- hosted observability
- RAG-specific evaluation depth
- massive academic benchmark coverage
- red-team/security breadth
- model leaderboard authority

## Validated Main Risks

The market already has broad LLM evaluation platforms and frameworks. The risk
is not that there is no need; the risk is drifting into a crowded category.
Promptfoo positions itself as an open-source CLI/library for LLM evals and
red-teaming with many providers, caching, CI, sharing, and a local/private
workflow. DeepEval covers local evals, metrics, tracing, retry behavior, and a
cloud reporting path. LangSmith covers offline evaluation, datasets,
observability, online monitoring, human review, code evaluators, and
LLM-as-judge. OpenAI Evals provides an eval framework, benchmark registry, and
custom/private eval flows.

This validates the narrow wedge: do not sell this as a general eval framework.
Sell it as the fastest local preflight for live model APIs: quality gate,
latency, cost, and provider quirks before a model switch.

### Critical Risks

- **Positioning creep:** competing with full eval, tracing, red-team, or hosted
  observability tools would erase the niche. Keep the public story to
  "smoke-test live LLM models before production."
- **Secrets and result safety:** local-first only matters if users trust that
  configs, headers, environment variables, failed responses, and artifacts are
  handled safely. Add central redaction, explicit `.env*` behavior, result
  scanning, and tests for `API_KEY`, `TOKEN`, `SECRET`, `Authorization`, and
  custom headers.
- **Cost/request surprise:** live calls are paid calls. Interactive mode,
  `--dry-run`, and reports must make request count, warmups, load expansion,
  and estimated cost impossible to miss. Load tests should stay opt-in or very
  clearly labeled.

### High Risks

- **Weak default tests:** built-in smoke tests must feel like real production
  failure modes, not arbitrary trivia. Keep tightening profiles around
  structured output, exact classification, short chat, basic reasoning, load,
  and custom prompt packs.
- **Unclear failure semantics:** users must instantly understand the difference
  between `API FAIL` and `API OK / TEST FAIL`. API failures mean request,
  credential, provider, network, rate-limit, or unsupported-parameter problems.
  Test failures mean the model responded but did not satisfy the validator.
- **Interactive friction:** the CLI must stay faster than opening a notebook or
  writing a one-off script. The run plan should show models, tests,
  repetitions, stop mode, response retention, request count, and cost before
  spending money.
- **Killer workflow missing from the first impression:** catalog discovery is
  the most differentiated path. Make "a new model appeared; test it against my
  prompts now" a first-class documented workflow, not an advanced feature.

### Medium Risks

- **Validation opacity:** strict validators can reject outputs that look almost
  correct. Reports should preserve failed examples by default, show evaluator
  reasons, and explain the exact assertion that failed.
- **Provider transient failures:** live APIs have rate limits and intermittent
  failures. Add provider-aware retry/backoff classification without hiding
  billable failures.
- **Setup complexity:** config editing, provider credentials, presets, and
  custom tests can slow first use. `llm-bench init`, guided provider setup, and
  copy-pasteable examples are part of the product, not polish.

## OSS and Promotion Plan

### Project Identity

Use a clear one-liner everywhere:

> Smoke-test live LLM models before they hit production.

Alternative:

> A local CLI to test-drive LLM APIs for quality, latency, and cost.

### README First Screen

The README should show:

1. One-line value proposition.
2. A short terminal screenshot or text table.
3. A 60-second quick start.
4. A clear comparison: "not a full eval platform; a model test drive."
5. A live-model example with pass/fail, latency, and cost.

### Demo Assets

Create:

- A terminal GIF of interactive mode.
- A screenshot of the final pass/fail table.
- A sample HTML report once available.
- A small public demo config using only mock provider or cheap models.

### Launch Channels

Initial OSS promotion:

- GitHub README and topics:
  - `llm`
  - `benchmark`
  - `evals`
  - `openai`
  - `anthropic`
  - `gemini`
  - `openrouter`
  - `cli`
  - `model-selection`
- Hacker News: "Show HN: A local CLI to smoke-test LLM APIs before switching models"
- Reddit:
  - r/LocalLLaMA
  - r/OpenAI
  - r/ClaudeAI
  - r/MachineLearning
  - r/ExperiencedDevs, if framed around model migration
- X/LinkedIn short demos:
  - "I tested 15 live models against my own structured-output prompt in one command."
- Dev.to / blog post:
  - "How to choose an LLM model without trusting leaderboards"

### Content Angles

- "Leaderboards do not tell you if a model passes your prompt."
- "The cheapest model is only cheap if it follows your schema."
- "Provider JSON mode is not portable. Your smoke tests should catch that."
- "Before switching from GPT to Gemini/Qwen/MiniMax, run one local command."

### Contributor-Friendly Issues

Label good first issues:

- Add provider pricing entries.
- Add provider preset mappings.
- Add validators.
- Add built-in smoke test cases.
- Improve report formatting.
- Add docs examples.

Label advanced issues:

- HTML report.
- Baseline regression thresholds.
- GitHub Actions annotations.
- Catalog diff/watch.
- Provider-specific diagnostics.

### Community Trust

- Keep unit tests deterministic and offline.
- Make live API tests optional.
- Be explicit about paid API calls.
- Do not collect telemetry by default.
- Keep examples synthetic and safe to publish.
- Include result files in `.gitignore` recommendations.

## Success Metrics

Useful project metrics:

- Time from install to first useful result under 5 minutes.
- One-command smoke test against at least 5 providers.
- Provider presets reduce structured-output failures.
- Users can validate a new model without writing Python.
- CI mode can block a model migration on quality/cost regression.

OSS traction metrics:

- GitHub stars from developer communities.
- External provider preset contributions.
- Issues opened for new provider quirks.
- Shared result screenshots.
- Blog posts or examples comparing real model migrations.

## Non-Goals

- Replace Promptfoo, DeepEval, Ragas, LangSmith, or OpenAI Evals.
- Become a hosted monitoring product.
- Maintain an authoritative public model leaderboard.
- Run large academic benchmark suites.
- Require users to write Python for basic validation.
