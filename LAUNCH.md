# Launch Material

## Positioning

**LLM Speed Bench is the local, cross-provider preflight for a model switch.**

It answers three questions before a model reaches production: does it pass the
actual prompt, how fast is it from this environment, and what does it cost?
It is not a hosted observability product or a general-purpose evaluation suite.

## GitHub Release Copy

### LLM Speed Bench 1.0.0

LLM Speed Bench 1.0.0 is a stable local CLI for smoke-testing live models across
OpenAI, Anthropic, Gemini, xAI, OpenRouter, and OpenAI-compatible providers.

- Run deterministic prompt validation alongside latency, tokens, and cost.
- Preview nominal and retry-expanded request/cost bounds before spending.
- Keep credentials and results local, with artifact redaction and no-save CI
  mode.
- Start without a key using the deterministic mock-provider demo.

## Announcement Post

New model releases are easy to try and expensive to trust. LLM Speed Bench is a
local CLI for the decision immediately before a model switch: run your actual
prompt against candidate providers, validate the output, and compare latency
and cost from the environment that will use it. Version 1.0.0 adds a no-key
mock demo, retry-aware run planning, CI-friendly no-save mode, and hardened
artifact redaction.

## First Three Posts

1. **Before changing models:** a short terminal walkthrough from dry run to
   validated result.
2. **New model, same prompt:** compare a provider's new catalog model against
   the incumbent using a custom deterministic validator.
3. **Cost control in CI:** show request/cost ceilings, retry-expanded planning,
   `--no-save`, and non-zero exits.

## Launch Success Signals

- Installs that complete the mock demo.
- GitHub issues containing real provider compatibility reports.
- Config examples contributed for production prompt shapes.
- Repeat use of dry-run and CI workflows, not vanity traffic alone.
