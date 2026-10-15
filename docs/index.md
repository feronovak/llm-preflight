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

## Tested models

| Model | Checks passed | Mean latency | Est. cost / 16 | Last tested | Connection |
|---|---:|---:|---:|---|---|
| GPT-6 Astra | 16/16 | 2.184s | $0.024610 | 2026-09-28 | OpenAI |
| GPT-6.1 Sol | 16/16 | 1.674s | $0.005112 | 2026-10-14 | OpenAI |
| GPT-6 Luna | 16/16 | 2.150s | $0.000353 | 2026-10-14 | OpenAI |
| Claude Opus 5.5 | 16/16 | 1.985s | $0.013220 | 2026-10-14 | Anthropic |
| Claude Sonnet 5.5 | 16/16 | 1.095s | $0.005740 | 2026-10-14 | Anthropic |
| Claude Haiku 5.5 | 16/16 | 0.934s | $0.000479 | 2026-10-14 | Anthropic |
| Gemini 4 Argon | 16/16 | 2.376s | $0.005546 | 2026-10-14 | Gemini |
| Gemini 3.8 Flash | 16/16 | 2.255s | $0.005666 | 2026-10-14 | Gemini |
| Gemini 3.1 Flash-Lite | 16/16 | 0.977s | $0.000588 | 2026-09-28 | Gemini |
| GLM 5.3 | 11/16 | 1.221s | — | 2026-10-14 | OpenRouter / Relace |
| GLM 5.3 Flash | 16/16 | 1.535s | $0.000178 | 2026-10-14 | OpenRouter / Relace |
| DeepSeek V4.1 Flash | 16/16 | 2.342s | $0.000745 | 2026-10-14 | OpenRouter / Relace |
| Qwen 3.8 Max 0902 | Request rejected | — | — | 2026-10-14 | OpenRouter / Alibaba US |
| Qwen 3.8 Flash | 5/16 | 1.077s | — | 2026-10-14 | OpenRouter / Alibaba US |

[Test details](guides/observed-model-comparison.md).

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
