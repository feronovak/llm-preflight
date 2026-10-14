# LLM Preflight documentation

**Last reviewed:** 2026-10-14 · **As of:** v2.21.2

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

Our current shortlist covers flagship and budget options across OpenAI,
Anthropic, Gemini, GLM, DeepSeek and Qwen. Start a balanced-model review with
**Sonnet 5.5 or GPT-6.1 Sol**; include **Opus 5.5** for a higher-cost candidate.
For a budget review, compare **GPT-6 Luna, Haiku 5.5, Qwen 3.8 Flash and
DeepSeek V4.1 Flash** against your own contract. Gemini 3.8 Flash and Qwen
3.8 Max are also measured alternatives. These are review candidates;
production promotion requires your application's evidence and approval.

The table shows the latest retained run of the same eight example routing and
JSON cases, twice per model. **Not run** means there is no live measurement;
it contributes no success, latency or cost claim. Model availability and
request support were reviewed on **2026-10-14**.

| Provider route | Exact API model ID | Observed date | Valid / 16 | Mean latency | Estimated cost / 16 |
|---|---|---|---:|---:|---:|
| Anthropic | `claude-opus-5-5` | 2026-09-28 | 16 | 2.041s | $0.012120 |
| Anthropic | `claude-sonnet-5-5` | 2026-10-07 | 16 | 1.390s | $0.005740 |
| Anthropic | `claude-haiku-5-5` | 2026-10-07 | 16 | 1.090s | $0.000481 |
| OpenAI | `gpt-6.1-sol` | 2026-09-30 | 16 | 2.071s | $0.004802 |
| OpenAI | `gpt-6-luna` | 2026-09-28 | 16 | 1.361s | $0.000350 |
| Gemini | `gemini-4-argon` | Not run | — | — | — |
| Gemini | `gemini-3.8-flash` | 2026-09-28 | 16 | 2.363s | $0.014768 |
| OpenRouter / Relace | `z-ai/glm-5.3` | 2026-09-30 | 14 | 0.948s | $0.001190 |
| OpenRouter | `z-ai/glm-5.3-flash` | Not run | — | — | — |
| OpenRouter | `deepseek/deepseek-v4.1-flash` | 2026-09-28 | 16 | 0.963s | $0.001863 |
| OpenRouter | `qwen/qwen3.8-max-0902` | 2026-09-28 | 16 | 4.186s | $0.012932 |
| OpenRouter | `qwen/qwen3.8-flash` | 2026-09-28 | 16 | 1.459s | $0.000274 |

**Known limits:** Haiku passed these 16 cases and 53/53 additional checks, but
its separate password-reset smoke was **5/6**. Sonnet's smoke was **6/6**.
GLM's **14/16** result includes an empty JSON answer and a wrong routing label;
it is a candidate to investigate, not a passing recommendation. The native
Z.ai, DeepSeek and Qwen routes have no measurements in this study.

Each cost is a token-based estimate for those 16 requests, not an invoice or
a current per-task price. September OpenAI estimates predate cache-write
accounting and can omit those charges. Settings and reasoning differ across
routes; calls ran in sequential blocks from one host. This small example does
not establish a stable quality, speed or cost ranking.

The [observed comparison](guides/observed-model-comparison.md)
retains all **27 measured** IDs, request settings and failure analysis.
Current availability also includes [GLM 5.3 Flash/FlashX](https://docs.z.ai/guides/vlm/glm-5.3-flash),
`z-ai/glm-5.3-flashx`, [GLM 5.3 Prime](https://openrouter.ai/z-ai/glm-5.3-prime),
`z-ai/glm-5.3-prime`, and [Qwen 3.8 Max Prime](https://openrouter.ai/qwen/qwen3.8-max-prime),
`qwen/qwen3.8-max-prime`. These variants are **unmeasured** here; their
availability does not transfer another row's result.

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
