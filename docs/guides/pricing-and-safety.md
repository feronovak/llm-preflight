# Tests, pricing, and safety

## Built-in tests and validation

Built-in packs are `quick-migration-check`, `exact-routing-check`,
`structured-output-check`, `numeric-instruction-check`, and
`concurrency-health-check`. The concurrency pack intentionally expands work at
concurrency 1, 5, and 10; keep it separate from normal interactive-latency
comparisons.

Use `--migration-check` for the smallest real response check. It runs the three
`quick-migration-check` cases once per selected model, with no warmups and
concurrency one.
It answers “does this candidate respond and meet a basic contract here?” before
a model switch. It is not a reliable latency ranking; use several repetitions
for that, and run `concurrency-health-check` separately for concurrency behaviour.

Use `"profiles": "all"` for the full built-in suite or select a mixed subset
with `--tests`. For a low-cost production-shaped first pass, use
`--tests agent-smoke --smoke`; it selects five functional checks and excludes
load testing. The evaluator supports exact matches, controlled values, numeric
answers with tolerances, JSON object/array shape and count checks, size and
Markdown limits, regular expressions, contains checks, and a structural
`json_schema` subset. Validation failures are test failures even when the API
responded.

## Fair comparisons and retries

Keep the prompt, system prompt, temperature, and maximum output fixed. Run from
the same host, pin dated model IDs where possible, and use at least 20 measured
repetitions for meaningful latency comparison.

Retryable rate limits, selected 5xx responses, temporary network failures, and
timeouts retry once by default. Configure `request.retry` to change attempts,
backoff, and bounded jitter. Plans include every selected profile case, warmup,
request override, and retry-expanded cost ceiling; results record retry counts
and final failure categories. Latency and TTFT for a successful request measure
its final network attempt, not prior retry backoff; retry counts remain visible
so a fast recovered request is not mistaken for an uninterrupted one. Malformed
provider responses are deterministic failures and are not retried.
Socket-level connection failures are retried according to `retry_on: network`;
the classification uses the transport exception rather than provider-specific
error wording.

A catalogue probe is different from a benchmark: it sends one minimal request
only after explicit confirmation, to establish whether a selected text candidate
has a usable provider adapter. It may be charged. The local capability ledger
stores the outcome and safe request shape, not response text; a changed provider
fingerprint expires the prior probe result.

## Pricing confidence

OpenRouter pricing comes from its live catalog and is labelled `openrouter
routed` with authoritative confidence: it applies when the benchmark is routed
through OpenRouter. Selected direct OpenAI, Gemini, Anthropic, and xAI prices
are maintained as timestamped `official snapshot` records. Unknown prices stay
unknown; the tool never silently treats an OpenRouter route as a direct-provider
price.
Explicit per-model prices override the registry. When a provider reports cache-hit
tokens, the estimate applies the model's cached-input rate. Gemini 3.1 Pro
Preview also uses its published per-request 200k-input tier, including thinking
tokens in output usage. Estimates still exclude taxes, cache-storage fees, tool
fees, and account-specific discounts not reported in usage.

An explicit override is reviewed evidence, not a timeless number. Include a
source and date so the coverage gate can assess it:

```json
{
  "provider": "openai",
  "model": "candidate-model",
  "input_cost_per_million": 2.5,
  "output_cost_per_million": 15,
  "pricing_metadata": {
    "source": "official provider pricing",
    "as_of": "2026-08-11"
  }
}
```

Run `--dry-run` or `--pricing-check` after pricing edits. The coverage report
lists every selected direct model and OpenRouter route as `priced`, `undated`,
`stale`, or `unknown`, together with its source and remediation. An invalid
date is `undated` and names the date correction required. Mock fixtures remain
in the report as pricing-exempt because they cannot create paid provider usage.
Treat unknown or stale prices as a reason not to compare cost rankings.
`--pricing-check` exits nonzero for those two states; it also exits nonzero for
an undated price when `"require_current_pricing": true` is set.

That setting prevents a paid run until every billable selected route has a
current dated price. It also applies the freshness window to dated user
overrides, so a one-time override cannot satisfy the gate indefinitely. For a
stale direct-provider snapshot, upgrade `llm-preflight` once its official
snapshot has been refreshed, or supply reviewed override evidence; a refresh
write does not permanently freeze an older bundled snapshot.

## Snapshot verification

The bundled direct-provider snapshot is release-reviewed evidence. Each model
entry records its provider's primary `source_url` and an `as_of` review date in
the resolved `pricing_metadata`. When refreshing it, verify every retained
model's standard synchronous input and output rates against that URL, update
the value, `as_of`, and source URL together, then run the snapshot coverage
test and `--pricing-check` before release. Do not re-date an entry whose rate
or availability cannot be verified from its recorded primary source; remove it
from the snapshot so the normal unknown-price remediation is shown instead.

## Sensitive data

Secrets are read from environment variables or the selected env file. The CLI
redacts common secret names, custom headers, dry-run output, saved results, and
provider errors. Prompts, model metadata, and retained failed responses can
still contain business data: review result artifacts before sharing them.

Never commit `.env.production`, raw results, private prompts, or provider
responses. See [SECURITY.md](../../SECURITY.md) to report a vulnerability.
