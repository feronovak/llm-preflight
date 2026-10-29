# When to use LLM Preflight

**Last reviewed:** 2026-10-27 · **As of:** v2.23.0

LLM Preflight is for a local integration change: a model ID, provider route,
prompt, request option, tool definition, schema, parser, or validation rule.
It answers whether that configured contract works from your environment at an
understood bounded cost. Treat the
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

## Compare the job before choosing a tool

For a support-routing change, use LLM Preflight to check the accepted `billing`
and rejected `sales` fixtures, inspect the route and price evidence, and plan a
bounded model request. A local fixture or mock verifies the configured validator;
it does not establish provider quality or production approval.

For a reusable dataset of outputs, prompts and scoring rules, an evaluation
framework can be a better fit. [Promptfoo assertions](https://www.promptfoo.dev/docs/configuration/expected-outputs/)
cover equality, JSON shape and other metrics. Its [Echo provider](https://www.promptfoo.dev/docs/providers/echo/)
can apply assertions to existing outputs without generating new ones. Both tools
can check a label fixture; choose the workflow that fits the review you need.
This overlap does not establish superiority or statistical model quality.

For production request traces, prefer instrumentation and an observability
system. [Langfuse tracing](https://langfuse.com/docs/observability/get-started)
records application spans and generations in a cloud or self-hosted deployment.
LLM Preflight's saved preflight results do not replace production traces.

For provider resource administration or direct API exploration, prefer the
provider's own tools. The [OpenAI CLI](https://developers.openai.com/api/docs/libraries/openai-cli)
exposes API and administrative operations; its [model commands](https://developers.openai.com/api/reference/cli/resources/models)
list, retrieve and delete provider model resources. Those are different jobs
from checking a cross-provider application contract before a change.

These are workflow comparisons based on documented capabilities and local
fixture checks. They are not adoption evidence, performance rankings or claims
that any tool is exclusive to one job.
