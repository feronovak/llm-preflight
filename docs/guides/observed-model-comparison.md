# Observed model comparison: support-routing example

**Last reviewed:** 2026-09-28 · **As of:** v2.18.2

**Study date:** 2026-09-28 · **Scope:** 24 selected API model IDs, 16 paid requests per ID

This is a dated example of using LLM Preflight to narrow a model shortlist. It
does not certify these models, rank general intelligence, or approve a route for
another application. The tested support tickets and JSON rules came from this
repository's examples and variants; they are not confirmed production traffic.
The underlying per-request artifacts are retained locally by the maintainer
and excluded from the public repository because failed responses and run
metadata can contain sensitive information. This page publishes aggregates
and the request method, not an independently auditable provider invoice.

## Method

- Eight support-routing and JSON cases were run twice per model, with no
  warmups, one attempt, concurrency one, and a 512-token output limit.
- These runs did not set `temperature`. The Sonnet 5.5 row therefore does not
  test that request parameter; 2.18.2 omits it from native Sonnet 5.5 requests.
- Validation checked the configured exact labels or raw JSON contract. A
  provider request can succeed while the returned response fails that
  contract. The JSON cases did not use native schema output; a real app should
  use its own request settings and parser.
- Qwen3.8 Flash used `reasoning.enabled: false` through OpenRouter after a
  32-token default-reasoning probe produced no visible answer. The other five
  OpenRouter routes used default reasoning. An exact model ID alone therefore
  does not reproduce every row's request.
- Cost is estimated from reported token usage and the reviewed price snapshot:
  direct-provider official rates or the 2026-09-28 OpenRouter catalogue rates.
  It is the cost of these 16 calls, not a task price or invoice. OpenRouter can
  choose different hosting endpoints; the selected endpoint was not recorded.
- Runs occurred in sequential blocks from one host. Sixteen calls per model
  do not establish stable latency or quality rankings.

## Observed results

| Provider | Exact API model ID | Valid / 16 | Mean latency | Estimated cost / 16 |
|---|---|---:|---:|---:|
| OpenAI | `gpt-5.6-sol` | 16 | 1.480s | $0.008604 |
| OpenAI | `gpt-5.6-terra` | 16 | 1.224s | $0.005084 |
| OpenAI | `gpt-5.6-luna` | 16 | 1.209s | $0.000507 |
| OpenAI | `gpt-6-sol` | 16 | 1.865s | $0.005392 |
| OpenAI | `gpt-6-luna` | 16 | 1.361s | $0.000350 |
| OpenAI | `gpt-6-astra` | 16 | 2.184s | $0.024610 |
| Anthropic | `claude-opus-4-8` | 16 | 1.367s | $0.014815 |
| Anthropic | `claude-opus-5-5` | 16 | 2.041s | $0.012120 |
| Anthropic | `claude-fable-5-1` | 16 | 3.170s | $0.029250 |
| Anthropic | `claude-sonnet-5` | 14 | 1.821s | $0.006396 |
| Anthropic | `claude-sonnet-5-5` | 16 | 1.258s | $0.005740 |
| Anthropic | `claude-haiku-4-5-20251001` | 6 | 0.940s | $0.002816 |
| Gemini | `gemini-3.5-flash` | 15 | 2.406s | $0.047097 |
| Gemini | `gemini-3.8-flash` | 16 | 2.363s | $0.014768 |
| Gemini | `gemini-3.1-flash-lite` | 16 | 0.977s | $0.000588 |
| Gemini | `gemini-3.1-pro-preview` | 16 | 4.140s | $0.064476 |
| xAI | `grok-4.7` | 16 | 2.476s | $0.014304 |
| xAI | `grok-4.6` | 16 | 5.496s | $0.010674 |
| OpenRouter | `qwen/qwen3.8-max-0902` | 16 | 4.186s | $0.012932 |
| OpenRouter | `qwen/qwen3.8-flash` | 16 | 1.459s | $0.000274 |
| OpenRouter | `deepseek/deepseek-v4-pro-0813` | 16 | 3.768s | $0.004166 |
| OpenRouter | `deepseek/deepseek-v4.1-flash` | 16 | 0.963s | $0.001863 |
| OpenRouter | `moonshotai/kimi-k3` | 16 | 3.916s | $0.034866 |
| OpenRouter | `moonshotai/kimi-k2.6` | 15 | 3.005s | $0.012846 |

## What the lower scores mean

- **Claude Sonnet 5** returned correct fields inside Markdown fences on two
  calls. The configured raw-JSON parser rejected the formatting.
- **Claude Haiku 4.5** returned fenced JSON in most failed cases. Two invoice
  responses also selected `account` where this example expected `billing`;
  the prompt did not define that mapping clearly, so this part of the score
  reflects a weak case specification as well as the expected-value mismatch.
- **Gemini 3.5 Flash** produced one incomplete JSON response at the 512-token
  limit. A separate two-request check at 1024 tokens passed.
- **Kimi K2.6** used all 512 output tokens on one request and returned no
  visible JSON. Disabling reasoning passed a two-request follow-up, but a
  full 16-case rerun scored 14/16 because two JSON responses were fenced.
  The table keeps the original default-reasoning 15/16 result.

These are request/parser and case-expectation observations. They do not show
that a model is generally unreliable or that another parser would reject the
same content.

## Use the result in your own project

1. Select a small candidate set and one incumbent. Treat this table as a way
   to choose what to examine, rather than as an approval list.
2. Build checks from your application's actual request, output schema,
   parser, and representative success and failure cases. Use the
   [project integration guide](../getting-started/project-integration.md) and
   [custom contract guide](output-contracts.md).
3. Run `--contract-check`, `--doctor`, `--pricing-check`, and `--dry-run` before
   any paid request. Keep model IDs, routing options, token limits, retries,
   current price evidence, and request/cost caps in the review.
4. Run the selected comparison only after the plan is reviewed. Keep its
   result and compare it with a compatible baseline in your own environment.
   An engineer then decides whether to add a model to that project's approved
   list. The [catalogue guide](model-catalog.md) shows this workflow.

LLM Preflight's unit suite uses deterministic fixtures for provider protocols,
validators, and decision behavior. These live model observations belong in an
optional, bounded comparison run; they are not assertions that `make test`
should repeat against paid, changing providers.
