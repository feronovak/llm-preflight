# Official pricing snapshots and native routes

**Last reviewed:** 2026-09-25 · **As of:** v2.17.1

This is not a ranking and not a complete list of models you can call. The
catalogue can discover any ID a supported provider lists. The table below is
the set of **direct-provider prices re-read against official pages for
2.16.0** and carried into 2.17.1. Use it to see what `official snapshot`
coverage the current release ships, then discover and probe the IDs you
actually run.

Package version: **2.17.1**. The listed official price rows were last re-read
for 2.16.0; 2.17.1 carries those snapshots without a new price review.

## Native routes

| Provider | Default key | Role |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | Text chat / Responses |
| `anthropic` | `ANTHROPIC_API_KEY` | Text chat |
| `gemini` | `GEMINI_API_KEY` | Text chat |
| `xai` | `XAI_API_KEY` | Text chat |
| `deepseek` | `DEEPSEEK_API_KEY` | Text chat (OpenAI-compatible) |
| `qwen` | `DASHSCOPE_API_KEY` | Text chat (international DashScope) |
| `openrouter` | `OPENROUTER_API_KEY` | Routed catalog; live prices when present |
| `openai_compatible` | `api_key_env` | Caller-supplied OpenAI-compatible base URL |
| `typesafe` | `TYPESAFE_API_KEY` | Catalogue-only typed-decision (Jev); not text smoke |
| `mock` | — | Local fixtures; no provider call |

`catalog init` can include `openai`, `anthropic`, `gemini`, `xai`, `openrouter`,
`deepseek`, `qwen`, and `typesafe`.

## Official snapshots in this release

Rates are USD per million tokens. `as_of` is the date this package last
checked the official page. Long-context bands, cache rates, and DeepSeek peak
hours live in code; this table is the headline input/output pair.

| Provider | Model ID | Input | Output | Last checked |
|---|---|---:|---:|---|
| `openai` | `gpt-6-astra` | 10.00 | 50.00 | 2026-09-20 |
| `openai` | `gpt-6-sol` | 2.00 | 10.00 | 2026-09-22 |
| `openai` | `gpt-6-luna` | 0.10 | 0.50 | 2026-09-22 |
| `openai` | `gpt-5.6-sol` | 4.00 | 20.00 | 2026-08-30 |
| `openai` | `gpt-5.6-terra` | 2.00 | 12.00 | 2026-08-30 |
| `openai` | `gpt-5.6-luna` | 0.20 | 1.20 | 2026-08-30 |
| `openai` | `gpt-5.5` | 5.00 | 30.00 | 2026-08-30 |
| `openai` | `gpt-5.4-mini` | 0.75 | 4.50 | 2026-08-30 |
| `openai` | `gpt-5.4-nano` | 0.20 | 1.25 | 2026-08-30 |
| `openai` | `gpt-4.1` | 2.00 | 8.00 | 2026-08-30 |
| `openai` | `gpt-4.1-mini` | 0.40 | 1.60 | 2026-08-30 |
| `openai` | `gpt-4.1-nano` | 0.10 | 0.40 | 2026-08-30 |
| `anthropic` | `claude-fable-5-1` | 10.00 | 50.00 | 2026-09-20 |
| `anthropic` | `claude-fable-5` | 10.00 | 50.00 | 2026-08-30 |
| `anthropic` | `claude-opus-5-5` | 4.00 | 20.00 | 2026-09-22 |
| `anthropic` | `claude-opus-5` | 5.00 | 25.00 | 2026-08-30 |
| `anthropic` | `claude-opus-4-8` | 5.00 | 25.00 | 2026-08-30 |
| `anthropic` | `claude-sonnet-5` | 2.00 | 10.00 | 2026-08-30 |
| `gemini` | `gemini-3.8-flash` | 0.75 | 3.75 | 2026-09-20 |
| `gemini` | `gemini-3.7-flash` | 0.75 | 3.75 | 2026-08-30 |
| `gemini` | `gemini-3.5-flash` | 1.50 | 9.00 | 2026-08-30 |
| `gemini` | `gemini-3.1-pro-preview` | 2.00 | 12.00 | 2026-08-30 |
| `gemini` | `gemini-3.1-flash-lite` | 0.25 | 1.50 | 2026-08-30 |
| `xai` | `grok-4.7` | 2.00 | 6.00 | 2026-09-22 |
| `xai` | `grok-4.6` | 2.00 | 6.00 | 2026-08-30 |
| `xai` | `grok-4.5` | 2.00 | 6.00 | 2026-08-30 |
| `xai` | `grok-4.3` | 1.25 | 2.50 | 2026-08-30 |
| `deepseek` | `deepseek-flash` | 0.30 | 1.20 | 2026-09-20 |
| `deepseek` | `deepseek-v4-pro` | 1.32 | 3.96 | 2026-09-20 |
| `qwen` | `qwen3.8-max` | 2.00 | 6.00 | 2026-09-20 |
| `qwen` | `qwen3.8-flash` | 0.15 | 0.47 | 2026-09-20 |
| `qwen` | `qwen3.7-plus` | 0.40 | 1.60 | 2026-09-20 |
| `typesafe` | `jev-latest` | 0.042 | 0.00 | 2026-09-20 |
| `typesafe` | `jev-1.13.0` | 0.042 | 0.00 | 2026-09-20 |

DeepSeek rows use peak cache-miss rates. Qwen 3.7 Plus has a higher band above
256k input. GPT-6 and several Grok/Gemini IDs have long-context bands. See
[`pricing.py`](../../llm_preflight/pricing.py) and
[pricing and safety](pricing-and-safety.md).

## Gaps vs this documentation version

These IDs are **not** in the snapshot table because they are not public
first-party routes we can price honestly:

| Gap | Status as of v2.17.1 |
|---|---|
| Gemini 4 | No public API model ID or price table. Public Gemini remains 3.x. |
| Kimi (Moonshot) native provider | Call via OpenRouter or `openai_compatible`. |
| GLM (Z.ai) native provider | Call via OpenRouter or `openai_compatible`. |
| TypeSafe Jev as a chat model | Catalogue-visible typed-decision route only. |
| Rows last checked 2026-08-30 | Still valid snapshots; not re-read for 2.16.0. Re-check before treating them as this week's official page. |

The [GitHub Marketplace Action guide](../automation/github-action.md) shows
how to install package 2.17.1 from its released Action tag. Docs whose
**As of** stamp is older than 2.17.1 were not re-read for this release; they
remain true for the behaviour they describe, not a claim that every page was
re-reviewed at 2.17.1.

See the [model catalogue](model-catalog.md) for discover → probe → smoke, and
[`examples/frontier-candidates.json`](../../examples/frontier-candidates.json)
for a current flagship example set.
