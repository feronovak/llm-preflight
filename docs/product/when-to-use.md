# When to use LLM Preflight

**Last reviewed:** 2026-08-31 · **As of:** v2.10.0

LLM Preflight is for a local integration change: a model ID, provider route,
prompt, request option, tool definition, schema, parser, or validation rule.
It answers whether that configured contract works from your environment at an
understood bounded cost. Read the [North star](../NORTH_STAR.md) and treat the
[decision contract](../reference/decision.md) as the automation boundary.

It is not a universal ranking of models. A passing run is evidence for one
account, network, prompt, and validator—not production approval.

| Use this when you need… | Prefer this instead when you need… |
|---|---|
| A small, local compatibility and contract check before changing an LLM integration. | An **evaluation suite** for broad datasets, scoring methodology, statistical comparison, or ongoing model-quality research. |
| A bounded price/request preview and an explicit paid smoke after human approval. | An **observability platform** for production tracing, telemetry retention, fleet dashboards, alerting, and incident investigation. |
| Provider-neutral evidence for a concrete application contract. | A **provider CLI** for provider administration, account settings, model management, or one-off API exploration. |

## What it deliberately does not do

- It does not host data, trace production traffic, or create a public
  leaderboard.
- It does not replace an evaluation suite where statistically meaningful
  quality claims are required.
- It does not approve a model, raise a budget, or make paid provider traffic
  implicit.

Start with the no-key mock demo, then use the smallest test that represents
your application contract. For a new model, follow the local lifecycle:
discover, inspect pricing and adapter evidence, probe deliberately, preview a
bounded smoke, and retain human approval separately.
