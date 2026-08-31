# LLM Preflight documentation

**Last reviewed:** 2026-08-31 · **As of:** v2.9.0

LLM Preflight is the local evidence gate for an LLM integration change. Use it
to check the contract your application actually needs, the latency and cost
from your environment, and the paid-work plan before production.

It is not a hosted evaluation platform, tracing system, or public leaderboard.
Results stay local unless you decide to attach or publish them.

## Start safely

- [Safe demo](getting-started/safe-demo.md) — run the no-key mock benchmark,
  then create a conservative provider starter.
- [A new model appeared](guides/model-catalog.md) — refresh provider metadata,
  then deliberately probe, benchmark, and approve a small candidate set.
- [Model change](guides/model-change.md) — compare an approved model and a
  candidate before changing production.
- [Output contracts](guides/output-contracts.md) — validate JSON, routing,
  parser behavior, and deterministic golden answers.

## Run and maintain preflights

- [Model catalogue](guides/model-catalog.md) — discover, probe, compare, and
  deliberately approve provider models.
- [Interactive runs](guides/interactive-runs.md) — select models and tests at
  the terminal, then review the paid-work plan.
- [Pricing and safety](guides/pricing-and-safety.md) — limits, pricing
  confidence, retries, response retention, and sensitive-data handling.

## Automate with confidence

- [CI and JSON output](automation/ci.md) — baselines, regression gates, and
  stable machine-readable evidence.
- [GitHub Actions starter](automation/ci.md#github-actions-starter) — a
  fork-safe mock workflow that uploads redacted evidence.
- [Marketplace Action](automation/github-action.md) — run no-spend doctor,
  pricing, and dry-run checks in a repository workflow.
- [Coding agents](automation/coding-agents.md) — a safe command sequence and
  decision rules for agents.
- [MCP server](automation/mcp.md) — give a coding agent local, bounded access
  to validation, planning, execution, and baseline diffs.

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
