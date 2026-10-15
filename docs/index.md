# LLM Preflight documentation

**Last reviewed:** 2026-10-15 · **As of:** v2.21.2

LLM Preflight is the local evidence gate for an LLM integration change. Use it
to check the contract your application actually needs, the latency and cost
from your environment, and the paid-work plan before production.

It is not a hosted evaluation platform, tracing system, or public leaderboard.
Results stay local unless you decide to attach or publish them.

## Start safely

- [Safe demo](getting-started/safe-demo.md) — run the no-key mock benchmark,
  then create a conservative provider starter.
- [Project integration](getting-started/project-integration.md) — adapt one
  application contract, reuse a project env file, and add a no-spend CI check.
- [Official snapshots](guides/current-snapshots.md) — native routes and the
  dated direct-provider prices, Gemini 4 Argon request settings and scheduled
  price changes; also Kimi native, Z.ai native discovery and Jev gaps.
- [Model retirements](guides/retirements.md) — bundled retirement snapshot, the three-state verdict, and the next command.
- [A new model appeared](guides/model-catalog.md) — refresh provider metadata,
  then deliberately probe, benchmark, and approve a small candidate set.
- [Model change](guides/model-change.md) — compare an approved model and a
  candidate before changing production.
- [Output contracts](guides/output-contracts.md) — validate JSON, routing,
  parser behavior, and deterministic golden answers.
- [Image-to-text contract inputs](guides/vision-inputs.md) — validate an image-to-text
  integration contract without scoring image quality.
- [Configuration](reference/configuration.md) — reuse an explicitly selected
  project env file without copying credentials.

## Run and maintain preflights

- [Model catalogue](guides/model-catalog.md) — discover, probe, compare, and
  deliberately approve provider models.
- [Model comparison](guides/observed-model-comparison.md) — dated
  results for **27 measured API model IDs**, including Haiku 5.5, Sonnet 5.5,
  GPT-6.1 Sol and GLM-5.3 through Relace, with request limits and failure analysis.
- [Interactive runs](guides/interactive-runs.md) — select models and tests at
  the terminal, then review the paid-work plan.
- [Pricing and safety](guides/pricing-and-safety.md) — limits, pricing
  confidence, retries, response retention, and sensitive-data handling.

## Current model shortlist

**Current passing shortlist:** Sonnet 5.5 and GPT-6.1 Sol for a balanced
review; Gemini 4 Argon and Gemini 3.8 Flash for a native Google route; Opus
5.5 as a higher-cost candidate. Budget candidates are **GPT-6 Luna, Haiku
5.5, GLM 5.3 Flash and DeepSeek V4.1 Flash**. All nine passed this example
contract. Production promotion requires your application's evidence and approval.

The **2026-10-14** run attempted the same eight support-routing and JSON cases
twice per model: **192 requests, no retries or warmups**. There were **163 API
successes and 160 valid outputs**. Mean latency covers successful API responses,
including contract failures. A dash means the metric is unavailable or cost
coverage is incomplete; it never means zero.

| Provider route | Exact API model ID | Observed date | Valid / 16 | Mean latency | Estimated cost / 16 |
|---|---|---|---:|---:|---:|
| Anthropic | `claude-opus-5-5` | 2026-10-14 | 16 | 1.985s | $0.013220 |
| Anthropic | `claude-sonnet-5-5` | 2026-10-14 | 16 | 1.095s | $0.005740 |
| Anthropic | `claude-haiku-5-5` | 2026-10-14 | 16 | 0.934s | $0.000479 |
| OpenAI | `gpt-6.1-sol` | 2026-10-14 | 16 | 1.674s | $0.005112 |
| OpenAI | `gpt-6-luna` | 2026-10-14 | 16 | 2.150s | $0.000353 |
| Gemini | `gemini-4-argon` | 2026-10-14 | 16 | 2.376s | $0.005546 |
| Gemini | `gemini-3.8-flash` | 2026-10-14 | 16 | 2.255s | $0.005666 |
| OpenRouter / Relace | `z-ai/glm-5.3` | 2026-10-14 | 11 | 1.221s | — |
| OpenRouter / Relace | `z-ai/glm-5.3-flash` | 2026-10-14 | 16 | 1.535s | $0.000178 |
| OpenRouter / Relace | `deepseek/deepseek-v4.1-flash` | 2026-10-14 | 16 | 2.342s | $0.000745 |
| OpenRouter / Alibaba US | `qwen/qwen3.8-max-0902` | 2026-10-14 | 0 | — | — |
| OpenRouter / Alibaba US | `qwen/qwen3.8-flash` | 2026-10-14 | 5 | 1.077s | — |

**Route and configuration failures:** Qwen Max's prepared request disabled
reasoning; the pinned endpoint requires it and rejected all 16 calls. This is
no model-quality measurement. Qwen Flash had **10 upstream rate limits** and
one invoice-routing failure among its six responses. GLM 5.3 had **three
upstream rate limits** and two invoice-routing failures among 13 responses.
These routes need investigation before promotion; native Z.ai, DeepSeek and
Qwen were not tested.

**Cost and settings:** The known token-cost subtotal is **$0.038129 for 163
responses**. The full total is **unknown** because 29 API errors returned no
usage; this is not an invoice. Argon used a **32,768**-token output/thinking
cap; every other model used **512**. Reasoning settings and routes differ,
and calls ran in sequential blocks from one host. Sixteen short cases do not
establish a stable quality, speed or cost ranking.

**Earlier evidence stays visible:** Haiku's separate 2026-10-07 password-reset
smoke was **5/6**; Sonnet's was **6/6**. GLM 5.3's 2026-09-30 run was
**14/16**. Those results are retained alongside this run, not replaced by it.
The September OpenAI estimates predate cache-write accounting and can omit
those charges.

The [observed comparison](guides/observed-model-comparison.md)
contains this run's method and failures plus all **27 measured** historical IDs.
The [aggregate data](data/model-comparison-2026-10-14.json)
records request settings, routes, usage, cost coverage and reproducible configs.
Passing response text was discarded; per-request verdicts and failure evidence
are retained privately.

[GLM 5.3 FlashX](https://docs.z.ai/guides/vlm/glm-5.3-flash),
`z-ai/glm-5.3-flashx`, [GLM 5.3 Prime](https://openrouter.ai/z-ai/glm-5.3-prime),
`z-ai/glm-5.3-prime`, and [Qwen 3.8 Max Prime](https://openrouter.ai/qwen/qwen3.8-max-prime),
`qwen/qwen3.8-max-prime`, remain **unmeasured** here. Another variant's
measurement does not establish their result.

## Automate with confidence

- [CI and JSON output](automation/ci.md) — baselines, regression gates, and
  stable machine-readable evidence.
- [Reviewable reports](guides/reports.md) — render saved results as offline
  HTML or a privacy-filtered GitHub job summary.
- [GitHub Actions starter](automation/ci.md#github-actions-starter) — a
  fork-safe mock workflow that uploads redacted evidence.
- [Marketplace Action](automation/github-action.md) — run no-spend doctor,
  pricing, and dry-run checks in a repository workflow.
- [Coding agents](automation/coding-agents.md) — a safe command sequence and
  decision rules for agents.
- [Git-aware change plans](automation/change-plans.md) — inspect local changes,
  then retain a bounded review receipt without granting execution authority.
- [MCP server](automation/mcp.md) — give a coding agent local, bounded access
  to validation, planning, execution, and baseline diffs; includes registry
  metadata and the repository plugin skill.

## Reference and help

- [Product map](FEATURE_MAP.md) — the source-verified capabilities in this
  release.
- [Changelog](../CHANGELOG.md) — shipped changes by version.
- [CLI reference](reference/cli.md)
- [Agent decision contract](reference/decision.md)
- [Configuration](reference/configuration.md) and
  [configuration schema](reference/configuration-schema.md)
- [Result JSON schema](reference/results.md)
- [Troubleshooting](operations/troubleshooting.md)
- [North star](NORTH_STAR.md) — mission, niche, boundaries, and product
  promise.
- [Product positioning](product/positioning.md) — stable pointer for older
  links.
- [When to use LLM Preflight](product/when-to-use.md) — choose it versus an
  evaluation suite, observability platform, or provider CLI.
- [Product decisions](DECISIONS.md)
