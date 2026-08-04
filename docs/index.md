# LLM Preflight documentation

LLM Preflight is the local evidence gate for an LLM integration change. Use it
to check the contract your application actually needs, the latency and cost
from your environment, and the paid-work plan before production.

It is not a hosted evaluation platform, tracing system, or public leaderboard.
Results stay local unless you decide to attach or publish them.

## Start safely

- [Safe demo](getting-started/safe-demo.md) — run the no-key mock benchmark,
  then create a conservative provider starter.
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
- [Coding agents](automation/coding-agents.md) — a safe command sequence and
  decision rules for agents.
- [MCP server](automation/mcp.md) — give a coding agent local, bounded access
  to validation, planning, execution, and baseline diffs.

## Reference and help

- [CLI reference](reference/cli.md)
- [Configuration](reference/configuration.md) and
  [configuration schema](reference/configuration-schema.md)
- [Result JSON schema](reference/results.md)
- [Troubleshooting](operations/troubleshooting.md)
- [Product positioning](product/positioning.md)
