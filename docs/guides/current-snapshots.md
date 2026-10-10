# Official pricing snapshots and native routes

**Last reviewed:** 2026-10-10 · **As of:** v2.20.0

This is not a ranking or a complete list of callable models. The catalogue can
discover any ID a supported provider lists. The table below records the
direct-provider price snapshots bundled in **2.19.1**. The
`gpt-6.1-sol` and `glm-5.3` rows were added in 2.19.0; each row records its own
official-source review date. Discover and probe the IDs you actually run.

Package version: **2.20.0**.

Version 2.19.1 adds Haiku 5.5 and updates Sonnet 5.5 cache pricing; the
Anthropic section below records the rates, request behavior and limits.

## Native routes

| Provider | Default key | Role |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | Text chat / Responses |
| `anthropic` | `ANTHROPIC_API_KEY` | Text chat |
| `gemini` | `GEMINI_API_KEY` | Text chat |
| `xai` | `XAI_API_KEY` | Text chat |
| `deepseek` | `DEEPSEEK_API_KEY` | Text chat (OpenAI-compatible) |
| `qwen` | `DASHSCOPE_API_KEY` | Text chat (international DashScope) |
| `zai` | `ZAI_API_KEY` | Text chat (standard Z.ai API) |
| `openrouter` | `OPENROUTER_API_KEY` | Routed catalog; live prices when present |
| `openai_compatible` | `api_key_env` | Caller-supplied OpenAI-compatible base URL |
| `typesafe` | `TYPESAFE_API_KEY` | Catalogue-only typed-decision (Jev); not text smoke |
| `mock` | — | Local fixtures; no provider call |

`catalog init` can include `openai`, `anthropic`, `gemini`, `xai`, `openrouter`,
`deepseek`, `qwen`, and `typesafe`.

## Bundled official snapshots

Rates are USD per million tokens. `as_of` is the date this package last
checked the official page. Long-context bands, cache rates, and DeepSeek peak
hours live in code; this table is the headline input/output pair.

| Provider | Model ID | Input | Output | Last checked |
|---|---|---:|---:|---|
| `openai` | `gpt-6-astra` | 10.00 | 50.00 | 2026-09-28 |
| `openai` | `gpt-6.1-sol` | 2.00 | 10.00 | 2026-09-30 |
| `openai` | `gpt-6-sol` | 2.00 | 10.00 | 2026-09-28 |
| `openai` | `gpt-6-luna` | 0.10 | 0.50 | 2026-09-28 |
| `openai` | `gpt-5.6-sol` | 4.00 | 20.00 | 2026-09-28 |
| `openai` | `gpt-5.6-terra` | 2.00 | 12.00 | 2026-09-28 |
| `openai` | `gpt-5.6-luna` | 0.20 | 1.20 | 2026-09-28 |
| `openai` | `gpt-5.5` | 5.00 | 30.00 | 2026-09-28 |
| `openai` | `gpt-5.4-mini` | 0.75 | 4.50 | 2026-09-28 |
| `openai` | `gpt-5.4-nano` | 0.20 | 1.25 | 2026-09-28 |
| `openai` | `gpt-4.1` | 2.00 | 8.00 | 2026-09-28 |
| `openai` | `gpt-4.1-mini` | 0.40 | 1.60 | 2026-09-28 |
| `openai` | `gpt-4.1-nano` | 0.10 | 0.40 | 2026-09-28 |
| `anthropic` | `claude-fable-5-1` | 10.00 | 50.00 | 2026-09-28 |
| `anthropic` | `claude-fable-5` | 10.00 | 50.00 | 2026-09-28 |
| `anthropic` | `claude-opus-5-5` | 4.00 | 20.00 | 2026-09-28 |
| `anthropic` | `claude-opus-5` | 5.00 | 25.00 | 2026-09-28 |
| `anthropic` | `claude-opus-4-8` | 5.00 | 25.00 | 2026-09-28 |
| `anthropic` | `claude-sonnet-5` | 2.00 | 10.00 | 2026-09-28 |
| `anthropic` | `claude-sonnet-5-5` | 2.00 | 10.00 | 2026-10-07 |
| `anthropic` | `claude-haiku-5-5` | 0.10 | 0.50 | 2026-10-07 |
| `anthropic` | `claude-haiku-4-5-20251001` | 1.00 | 5.00 | 2026-09-28 |
| `gemini` | `gemini-3.8-flash` | 0.75 | 3.75 | 2026-09-28 |
| `gemini` | `gemini-3.7-flash` | 0.75 | 3.75 | 2026-09-28 |
| `gemini` | `gemini-3.5-flash` | 1.50 | 9.00 | 2026-09-28 |
| `gemini` | `gemini-3.1-pro-preview` | 2.00 | 12.00 | 2026-09-28 |
| `gemini` | `gemini-3.1-flash-lite` | 0.25 | 1.50 | 2026-09-28 |
| `xai` | `grok-4.7` | 2.00 | 6.00 | 2026-09-28 |
| `xai` | `grok-4.6` | 2.00 | 6.00 | 2026-09-28 |
| `xai` | `grok-4.5` | 2.00 | 6.00 | 2026-09-28 |
| `xai` | `grok-4.3` | 1.25 | 2.50 | 2026-09-28 |
| `deepseek` | `deepseek-flash` | 0.30 | 1.20 | 2026-09-28 |
| `deepseek` | `deepseek-v4-pro` | 1.32 | 3.96 | 2026-09-28 |
| `qwen` | `qwen3.8-max` | 2.00 | 6.00 | 2026-09-28 |
| `qwen` | `qwen3.8-flash` | 0.15 | 0.47 | 2026-09-28 |
| `qwen` | `qwen3.7-plus` | 0.40 | 1.60 | 2026-09-28 |
| `zai` | `glm-5.3` | 1.40 | 4.40 | 2026-09-30 |
| `typesafe` | `jev-latest` | 0.042 | 0.00 | 2026-09-28 |
| `typesafe` | `jev-1.13.0` | 0.042 | 0.00 | 2026-09-28 |

DeepSeek rows use peak cache-miss rates. Qwen rows use USD list rates; the
Qwen 3.7 Plus source currently shows a temporary 20% discount, so this snapshot
is a conservative estimate for that model. It has a higher band above 256k
input. GPT-5.5, GPT-6 and several Grok/Gemini IDs have long-context bands.
Grok's long-context band starts at 200,000 input tokens. GPT-6.1 Sol
has a $0.10 cached-input rate for up to 272k input tokens and $0.20 above
that threshold. See
[`pricing.py`](../../llm_preflight/pricing.py) and
[pricing and safety](pricing-and-safety.md).

### Anthropic pricing and request updates in 2.19.1

Reviewed on **2026-10-07**. The
[Haiku 5.5 model page](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
documents `claude-haiku-5-5` with these standard synchronous USD rates per
million tokens:

| Total input length | Input | Cached input | Output |
|---|---:|---:|---:|
| Up to 100,000 tokens | 0.10 | 0.01 | 0.50 |
| Above 100,000 tokens | 0.50 | 0.05 | 2.50 |

The band applies to the full request, including cached input. Haiku 5.5 has
a 1M-token context window, up to 128K output tokens and adaptive thinking with
`medium` effort by default. The native text adapter omits `temperature`;
configure effort through `request.provider_options.anthropic.output_config`.
The model accepts images, but this project's Anthropic adapter remains text-only.

The [October 7 announcement](https://www.anthropic.com/claude-haiku-5-5)
also cuts `claude-sonnet-5-5` cache reads from $0.20 to **$0.10** per million
tokens. Its input and output rates remain $2 and $10. The announcement is
the updated snapshot source because the older Sonnet overview still lists
the previous cache-read rate.

Anthropic reports uncached input, cache reads and cache writes separately.
The adapter now sums them into total input and retains the cache-write count.
No Anthropic cache-write rate is bundled: five-minute and one-hour writes
have different prices. Supply a reviewed `cache_write_input_cost_per_million`
matching the configured cache lifetime, including any applicable input tiers,
or reported writes make the cost estimate unavailable.

### GPT-6.1 Sol pricing and request limits

The [official model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
was checked on 2026-09-30. Standard synchronous USD rates per million tokens:

| Input length | Input | Cached input | Cache writes | Output |
|---|---:|---:|---:|---:|
| Up to 272,000 tokens | 2.00 | 0.10 | 2.50 | 10.00 |
| Above 272,000 tokens | 4.00 | 0.20 | 5.00 | 15.00 |

The band applies to the full request, using total input tokens before cache
discounts. Reported cache reads and writes are priced separately; the no-spend
plan includes the possible write premium. Fast mode, Batch/Flex, regional
premiums, and tool charges require rates appropriate to those services.

The model has a 1,050,000-token context window and a 128,000-token maximum
output. Reasoning efforts are `low`, `medium` (default), `high`, `xhigh`, and
`max`; `none` and `minimal` are unsupported. The project omits `temperature`.
Chat Completions supports text requests; tool calling requires Responses.
The project's minimal Responses adapter currently accepts text requests.

### GLM-5.3 pricing and request limits

The [official Z.ai pricing page](https://docs.z.ai/guides/overview/pricing)
was checked on 2026-09-30: $1.40 input, $0.26 cached input and $4.40 output
per million tokens for the standard native API. Cache storage is temporarily
free; estimates exclude storage charges if that offer changes.
The route is `https://api.z.ai/api/paas/v4/chat/completions`, with
`provider: "zai"` and `ZAI_API_KEY`. Coding Plan subscription quotas and
OpenRouter routed prices are separate from these standard API rates.

[GLM-5.3's model guide](https://docs.z.ai/guides/llm/glm-5.3) documents
text-only input, a 1M-token context and up to 128K output tokens. Reasoning
is always enabled: `low`, `high`, and `max` are supported, with `max` the
default. The native adapter rejects disabled reasoning and unsupported
efforts before transport. Use `request.provider_options.zai.reasoning_effort`
to select `low` for the bounded comparison. Reported completion usage is
priced in full, including reasoning; internal reasoning text is excluded from
response validation.

The [dated comparison](observed-model-comparison.md) includes a measured
GLM-5.3 run through OpenRouter / Relace, with that host's separate prices.
The native Z.ai integration has deterministic fixture coverage; it has not
had a live run with native credentials.

Native Z.ai catalogue discovery is not implemented. Enter `glm-5.3` explicitly
for native runs, or discover `z-ai/glm-5.3` through OpenRouter using its live
route prices. A successful discovery is not an access or compatibility probe.

## Gaps vs this documentation version

These IDs are **not** in the snapshot table because they are not public
first-party routes we can price honestly:

| Gap | Status as of 2.19.1 |
|---|---|
| Gemini 4 | No public API model ID or price table. Public Gemini remains 3.x. |
| Kimi (Moonshot) native provider | Call via OpenRouter or `openai_compatible`. |
| Z.ai native catalogue | Native `glm-5.3` chat is supported; discovery uses OpenRouter or explicit model entries. |
| TypeSafe Jev as a chat model | Catalogue-visible typed-decision route only. |

The [GitHub Marketplace Action guide](../automation/github-action.md) shows
how to use a published package with its release-tag Action. Pages
with an older **As of** stamp still describe their stated version; they were
not all re-reviewed for 2.19.1.

See the [model catalogue](model-catalog.md) for discover → probe → smoke, and
[`examples/frontier-candidates.json`](../../examples/frontier-candidates.json)
for a current flagship example set.
