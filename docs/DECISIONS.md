# Product decisions

**Last reviewed:** 2026-08-30 · **As of:** v2.7.5

This is a short record of durable product boundaries. It explains the choices
that shape the public contract; implementation details belong with the code.

## Local-first execution

**Decision:** Run preflights locally against the user's configuration and
provider account; do not operate a hosted evaluation or telemetry service.

**Why:** The useful evidence is specific to the user's prompts, validators,
network, credentials, and provider access. Keeping results local also avoids a
new vendor in the decision path.

**Consequence:** Results are evidence for one environment, not universal model
rankings. Users choose whether to retain or share result artifacts.

## Standard-library runtime

**Decision:** Keep the published runtime dependency-free.

**Why:** A preflight tool should be simple to inspect, install, and run in
restricted CI and coding-agent environments.

**Consequence:** Provider clients and protocol handling are deliberately
small, and support is added only when it can be maintained without weakening
that installation and auditability property.

## Three-state decisions

**Decision:** A completed result is `pass`, `fail`, or `inconclusive`; unknown
evidence must not be represented as a pass.

**Why:** A successful request alone cannot prove the configured contract, and
missing or stale pricing prevents a reliable cost conclusion.

**Consequence:** Agents consume the schema-versioned JSON or MCP decision
object rather than parse terminal prose. See the [agent decision contract](reference/decision.md).

## Human approval for spend and promotion

**Decision:** Discovery and no-spend checks may be automated, but paid
generation, budget increases, and model approval remain explicit human
decisions.

**Why:** Account availability, acceptable cost, and production risk belong to
the person responsible for the integration.

**Consequence:** The tool previews retry-expanded requests and pricing before
live work, and a passing preflight never authorizes deployment on its own. See
[AI implementation testing](automation/agent-validation.md).

## Typed-decision models stay out of text preflight

**Decision:** Keep TypeSafe Jev and similar System One routes in the catalogue
for discovery and price review. Do not treat them as LLM candidates for smoke,
probe, frontier examples, or a chat adapter. A typed-decision contract checker
is a separate product slice, not another row in a text model switch.

**Why:** This tool checks an LLM integration contract: prompt in, text or
structured text out. Jev returns declared choices, scores, and probabilities
over `POST /v1/systemone` and does not generate chat. Putting it in the same
selection as GPT-6 or Qwen would invent a request shape the model cannot
satisfy.

**Consequence:** Catalogue type `decision` is visible and priced, then marked
`incompatible_catalog_type` for generic text smoke. Native TypeSafe discovery
remains opt-in through `catalog init`. Image, audio, and other non-text
catalogue types already follow the same pattern.
