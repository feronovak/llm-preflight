# North star

**Last reviewed:** 2026-09-08 · **As of:** v2.12.0

## Mission

Help engineers catch LLM integration regressions before shipping a change.

## Vision

Every LLM-related pull request carries reproducible evidence of compatibility,
latency, and cost.

## Positioning statement

LLM Preflight is a local CLI and CI tool that checks an application's LLM
contract and reports compatibility, latency, and estimated cost before a change
ships.

It is evidence for the user's account, environment, prompts, and validators;
it is not a universal ranking of models.

## Niche

The primary users are small engineering teams maintaining an AI feature:

- model IDs or provider routes;
- prompts, request options, and tool definitions;
- structured-output schemas and response parsers; or
- an approved model's cost or latency envelope.

Tool definitions are a change trigger because they can alter an application's
LLM behavior. LLM Preflight statically validates a deliberately portable
canonical tool schema, but it does not yet invoke tools or test agent
trajectories.

The narrow job is to answer: **does this concrete integration still meet its
contract from our environment, at an understood cost, before we ship it?**

## What it is not

LLM Preflight does not aim to be a hosted observability product, a tracing
system, a full evaluation framework, a broad red-team suite, a RAG platform, a
public leaderboard, or an autonomous deployment authority. A passing run is
evidence, not production approval.

## Product promise

An agent should be able to run a local, reviewable preflight before proposing
an LLM-related change as complete. Engineers own the decision; paid requests,
budget changes, and model approval remain explicit human decisions.

See [AI implementation testing](automation/agent-validation.md) for the
operational workflow, [LLM and coding-agent guide](automation/coding-agents.md)
for CLI semantics and guardrails, and [Product decisions](DECISIONS.md) for the
durable boundaries behind this direction.
