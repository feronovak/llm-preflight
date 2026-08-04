# Product positioning

## Mission

Make every LLM integration change evidence-based before production.

## Vision

AI-assisted software delivery where an agent can validate its LLM changes as
routinely as it runs tests, while people retain control of spend and production
approval.

## Positioning statement

LLM Preflight is the fast, local, cross-provider validation gate for
AI-powered application changes. It measures a real application's configured
contract against live model APIs: output validity, request reliability,
latency, usage, and estimated cost.

It is evidence for the user's account, environment, prompts, and validators;
it is not a universal ranking of models.

## Niche

The primary users are engineers and coding agents changing an AI feature:

- model IDs or provider routes;
- prompts, request options, and tool definitions;
- structured-output schemas and response parsers; or
- an approved model's cost or latency envelope.

The narrow job is to answer: **does this concrete integration still work from
our environment, at an understood cost, before we ship it?**

## What it is not

LLM Preflight does not aim to be a hosted observability product, a tracing
system, a full evaluation framework, a broad red-team suite, a RAG platform, a
public leaderboard, or an autonomous deployment authority. A passing run is
evidence, not production approval.

## Product promise

An agent should be able to run a local, reviewable preflight before proposing
an LLM-related change as complete. The preflight may automatically inspect and
test within the approved repository scope, but paid requests, budget changes,
and model approval remain explicit human decisions.

See [AI implementation testing](../automation/agent-validation.md) for the
operational workflow and [LLM and coding-agent guide](../automation/coding-agents.md) for CLI
semantics and guardrails.
