# Official pricing snapshots and native routes

**Last reviewed:** 2026-10-26 · **As of:** v2.23.0

This is not a ranking or a complete list of callable models. The catalogue can
discover IDs returned by supported metadata endpoints; configured native routes
are described in [native provider checks](native-providers.md).

Package version: **2.23.0**. The table records this version's reviewed
public-route rates, not account access or model quality.
All rows were reviewed on 2026-10-26 UTC and become stale on 2026-11-26.
Strict pricing then blocks execution. Explicit owner overrides retain their
own evidence and review dates.

The [latest comparison](observed-model-comparison.md) measured 19 native routes
on 2026-10-29, with eight cases each: 144 of 152 validated outputs, three contract
failures and five Kimi rate-limit errors. Historical **16/16** Gemini evidence
from October 14 is retained separately. Unmeasured added providers keep fixture-only
coverage; this pricing table does not establish access or model quality.

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
| `moonshot` | `MOONSHOT_API_KEY` | Kimi native text chat |
| `minimax` | `MINIMAX_API_KEY` | MiniMax native text chat |
| `mistral` | `MISTRAL_API_KEY` | Mistral native text chat |
| `cohere` | `COHERE_API_KEY` | Cohere native v2 text Chat |
| `openrouter` | `OPENROUTER_API_KEY` | Routed catalog; live prices when present |
| `openai_compatible` | `api_key_env` | Caller-supplied OpenAI-compatible base URL |
| `typesafe` | `TYPESAFE_API_KEY` | Catalogue-only typed-decision (Jev); not text smoke |
| `mock` | — | Local fixtures; no provider call |

`catalog init` can include `openai`, `anthropic`, `gemini`, `xai`, `openrouter`,
`deepseek`, `qwen`, `typesafe`, `moonshot`, `minimax`, `mistral`, and `cohere`.
Z.ai supports configured native models; no documented metadata discovery
endpoint is integrated.

Bundled native prices apply to the reviewed default base URL. A different
endpoint leaves the price unknown, including persisted official snapshots;
supply an explicitly reviewed override for that deployment. OpenRouter keeps
its own route prices. Kimi Highspeed is priced separately from standard Kimi.

## Bundled official snapshots

Rates are USD per million tokens. `as_of` is the actual review date. Long-context
bands and cache rates are recorded in the bundled ledger. The DeepSeek rows
use peak rates; Qwen uses Singapore/International list rates. Cohere's zero
row applies to its public Command A+ API under its documented rate limits;
it does not price Model Vault or another deployment.

| Provider | Model ID | Input | Output | Last checked |
|---|---|---:|---:|---|
| `openai` | `gpt-6-astra` | 10.00 | 50.00 | 2026-10-26 |
| `openai` | `gpt-6.1-sol` | 2.00 | 10.00 | 2026-10-26 |
| `openai` | `gpt-6.1-terra` | 1.00 | 5.00 | 2026-10-26 |
| `openai` | `gpt-6-sol` | 2.00 | 10.00 | 2026-10-26 |
| `openai` | `gpt-6-luna` | 0.10 | 0.50 | 2026-10-26 |
| `openai` | `gpt-5.6-sol` | 4.00 | 20.00 | 2026-10-26 |
| `openai` | `gpt-5.6-terra` | 2.00 | 12.00 | 2026-10-26 |
| `openai` | `gpt-5.6-luna` | 0.20 | 1.20 | 2026-10-26 |
| `openai` | `gpt-5.5` | 5.00 | 30.00 | 2026-10-26 |
| `openai` | `gpt-5.4-mini` | 0.75 | 4.50 | 2026-10-26 |
| `openai` | `gpt-5.4-nano` | 0.20 | 1.25 | 2026-10-26 |
| `openai` | `gpt-4.1` | 2.00 | 8.00 | 2026-10-26 |
| `openai` | `gpt-4.1-mini` | 0.40 | 1.60 | 2026-10-26 |
| `openai` | `gpt-4.1-nano` | 0.10 | 0.40 | 2026-10-26 |
| `anthropic` | `claude-fable-5-1` | 10.00 | 50.00 | 2026-10-26 |
| `anthropic` | `claude-fable-5` | 10.00 | 50.00 | 2026-10-26 |
| `anthropic` | `claude-opus-5-5` | 4.00 | 20.00 | 2026-10-26 |
| `anthropic` | `claude-opus-5` | 5.00 | 25.00 | 2026-10-26 |
| `anthropic` | `claude-opus-4-8` | 5.00 | 25.00 | 2026-10-26 |
| `anthropic` | `claude-sonnet-5` | 2.00 | 10.00 | 2026-10-26 |
| `anthropic` | `claude-sonnet-5-5` | 2.00 | 10.00 | 2026-10-26 |
| `anthropic` | `claude-haiku-5-5` | 0.10 | 0.50 | 2026-10-26 |
| `anthropic` | `claude-haiku-4-5-20251001` | 1.00 | 5.00 | 2026-10-26 |
| `gemini` | `gemini-4-argon` | 2.00 | 10.00 | 2026-10-26 |
| `gemini` | `gemini-3.8-flash` | 0.75 | 3.75 | 2026-10-26 |
| `gemini` | `gemini-3.6-flash` | 0.75 | 3.75 | 2026-10-26 |
| `gemini` | `gemini-3.1-pro-preview` | 2.00 | 12.00 | 2026-10-26 |
| `gemini` | `gemini-3.1-flash-lite` | 0.25 | 1.50 | 2026-10-26 |
| `xai` | `grok-4.7` | 2.00 | 6.00 | 2026-10-26 |
| `xai` | `grok-4.6` | 2.00 | 6.00 | 2026-10-26 |
| `xai` | `grok-4.5` | 2.00 | 6.00 | 2026-10-26 |
| `xai` | `grok-4.3` | 1.25 | 2.50 | 2026-10-26 |
| `deepseek` | `deepseek-flash` | 0.30 | 1.20 | 2026-10-26 |
| `deepseek` | `deepseek-v4-flash` | 0.30 | 1.20 | 2026-10-26 |
| `deepseek` | `deepseek-v4-flash-vision-exp` | 0.30 | 1.20 | 2026-10-26 |
| `deepseek` | `deepseek-v4-pro` | 1.32 | 3.96 | 2026-10-26 |
| `qwen` | `qwen3.8-max` | 2.00 | 6.00 | 2026-10-26 |
| `qwen` | `qwen3.8-flash` | 0.15 | 0.47 | 2026-10-26 |
| `qwen` | `qwen3.7-plus` | 0.40 | 1.60 | 2026-10-26 |
| `zai` | `glm-5.3` | 1.40 | 4.40 | 2026-10-26 |
| `zai` | `glm-5.3-flash` | 0.15 | 0.50 | 2026-10-26 |
| `zai` | `glm-5.3-flashx` | 0.37 | 1.25 | 2026-10-26 |
| `anthropic` | `claude-mythos-5-1` | 10.00 | 50.00 | 2026-10-26 |
| `moonshot` | `kimi-k3.1-pro` | 2.00 | 10.00 | 2026-10-26 |
| `moonshot` | `kimi-k3.1-pro-highspeed` | 4.00 | 20.00 | 2026-10-26 |
| `minimax` | `MiniMax-M3.1-Flash` | 0.15 | 0.60 | 2026-10-26 |
| `minimax` | `MiniMax-M3` | 0.30 | 1.20 | 2026-10-26 |
| `mistral` | `mistral-large-4` | 1.36 | 4.18 | 2026-10-26 |
| `mistral` | `mistral-large-4-0` | 1.36 | 4.18 | 2026-10-26 |
| `cohere` | `command-a-plus-05-2026` | 0.00 | 0.00 | 2026-10-26 |
| `typesafe` | `jev-latest` | 0.042 | 0.00 | 2026-10-26 |
| `typesafe` | `jev-1.13.0` | 0.042 | 0.00 | 2026-10-26 |
| `typesafe` | `jev-1.14.0` | 0.042 | 0.00 | 2026-10-26 |

DeepSeek rows use peak cache-miss rates. Qwen rows use USD list rates; the
Qwen 3.7 Plus source currently shows a temporary 20% discount, so this snapshot
is a conservative estimate for that model. It has a higher band above 256k
input. GPT-5.5, GPT-6 and several Grok/Gemini IDs have long-context bands.
Grok's long-context band starts at 200,000 input tokens. GPT-6.1 Sol
has a $0.10 cached-input rate for up to 272k input tokens and $0.20 above
that threshold. See
[`pricing.py`](../../llm_preflight/pricing.py) and
[pricing and safety](pricing-and-safety.md).

### GPT-6.1 Terra

The [official model page](https://developers.openai.com/api/docs/models/gpt-6.1-terra)
lists `gpt-6.1-terra` with a 1,050,000-token context window, up to 128,000
output tokens, text/image input and text output. Reasoning efforts are `none`,
`low`, `medium` (default), `high`, `xhigh` and `max`. Tool calling requires
Responses. This tool checks canonical tool definitions locally; it does not
execute tool calls or computer-use workflows.

The pricing row uses standard synchronous USD rates per million
tokens: $1 input, $0.05 cache reads, $1.25 cache writes (30-minute retention),
and $5 output. Above 272,000 total input tokens, input and cache rates double
and output costs $7.50 for the whole request. Twelve-hour cache writes, Fast,
Batch/Flex and regional processing require their own reviewed overrides.
The row becomes stale on 2026-11-26; strict pricing then blocks execution.
OpenAI retirement status remains unknown when its deprecations page does not
list an ID. Pricing coverage does not establish account access or approval.

The automatic discovery example includes Terra and recommends the Responses
adapter. Deterministic Chat Completions and Responses fixtures verify text
transport, configured Responses reasoning effort, complete response status,
cache usage and cost estimates. Terra and Sol each passed 8/8 cases in the
October 29 native comparison. Earlier Sol observations retain their original
route, settings and date.

### Native Qwen 3.8 corrections in source

The Max and Flash rows use Model Studio Singapore/International standard
input/output prices, rechecked against [Alibaba's pricing page](https://www.alibabacloud.com/help/en/model-studio/model-pricing)
on October 26. Other regions and deployment scopes require their own reviewed
overrides. For these models, [cache prices](https://www.alibabacloud.com/help/en/model-studio/context-cache)
must come from the account console. The source defaults their cache-hit rate
to `null`, so reported cache hits leave cost unknown until an explicit reviewed
override is supplied. QwenCloud cache prices are not substituted.

2.22.0 also uses `max_completion_tokens` for native Qwen 3.8
Max, Max-0902 and Flash, covering reasoning plus answer. Planner, doctor and
transport reject token-limit fields in provider options. An explicit legacy
`max_tokens` setting requires explicitly disabled thinking. The
[native smoke guide](native-chinese-models.md) supplies an example usable with
installed 2.21.2 by setting the combined-limit parameter and pricing override
explicitly. These fixes do not change OpenRouter requests or prior results.

### Gemini 4 Argon and Flash pricing transitions

Google's [October changelog](https://ai.google.dev/gemini-api/docs/changelog)
announces GA of `gemini-4-argon` on October 13. The
[migration guide](https://ai.google.dev/gemini-api/docs/latest-model) and
[pricing page](https://ai.google.dev/gemini-api/docs/pricing) document these
standard synchronous USD rates per million tokens, rechecked October 16 UTC:

| Model | Period | Input | Cached input | Output, including thinking |
|---|---|---:|---:|---:|
| `gemini-4-argon` | Through 2026-11-30 | 2.00 | 0.10 | 10.00 |
| `gemini-4-argon` | From 2026-12-01 | 4.00 | 0.20 | 20.00 |
| `gemini-3.6-flash`, `gemini-3.8-flash` | Through 2026-12-31 | 0.75 | 0.075 | 3.75 |
| `gemini-3.6-flash`, `gemini-3.8-flash` | From 2027-01-01 | 1.50 | 0.15 | 7.50 |

The tool selects these published rates using the current UTC date. A scheduled
price change does not renew snapshot freshness: strict pricing checks still
require a recent review. Explicit owner prices retain precedence.

Google deprecated `gemini-3.5-flash` and `gemini-3.7-flash` on October 8;
requests redirect to 3.6 and 3.8 respectively. Their endpoints are not shutting
down. The tool reports these aliases as retiring/inconclusive without a
shutdown date and leaves their effective price unknown, including saved
official prices. Use the direct replacement or supply an explicitly reviewed
owner rate. The September comparison remains historical evidence.

Argon shares a 1,048,576-token window across input, thinking and output.
The native GenerateContent adapter supports synchronous requests capped at
65,536 thinking-plus-output tokens. It omits ignored sampling parameters,
accepts `thinkingConfig.thinkingLevel` values `LOW`, `MEDIUM`, `HIGH`, and
rejects explicit `cachedContent` because only implicit caching is supported.
Provider options cannot override the output cap used in the plan. Background
long decode and server-managed conversation state are outside this adapter.

The tool keeps its existing 256-token default and any explicit output cap.
Google recommends at least 32,768 for existing applications with smaller caps;
review that increase against your own budget. The bounded
[`gemini-4-argon.json`](../../examples/gemini-4-argon.json) example explicitly
chooses 32,768 tokens, `LOW` thinking, one request, no retries and a $0.35
estimated-cost ceiling. Preview and check its local fixtures without spending:

```bash
llm-preflight examples/gemini-4-argon.json --contract-check --json
llm-preflight examples/gemini-4-argon.json --dry-run --json
```

The example's ceiling covers the introductory output allowance. After the
published increase it blocks execution until the owner reviews the limits;
the pricing freshness gate may block it earlier. Implicit cache discounts
are applied only when usage reports a cache hit.

### Anthropic pricing and request updates in 2.19.1

Reviewed on **2026-10-07** and rechecked unchanged on 2026-10-26. The
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

### OpenAI cache-write pricing correction

Rechecked October 16 UTC against each model's official page. Version 2.21.0
adds the published cache-write rate for these six models; their cache-read
rates and long-context input/output tiers were already bundled. Standard USD
write rates per million tokens:

| Model | Up to 272,000 total input tokens | Above 272,000 total input tokens |
|---|---:|---:|
| [`gpt-5.6-luna`](https://developers.openai.com/api/docs/models/gpt-5.6-luna) | 0.25 | 0.50 |
| [`gpt-5.6-terra`](https://developers.openai.com/api/docs/models/gpt-5.6-terra) | 2.50 | 5.00 |
| [`gpt-5.6-sol`](https://developers.openai.com/api/docs/models/gpt-5.6-sol) | 5.00 | 10.00 |
| [`gpt-6-astra`](https://developers.openai.com/api/docs/models/gpt-6-astra) | 12.50 | 25.00 |
| [`gpt-6-sol`](https://developers.openai.com/api/docs/models/gpt-6-sol) | 2.50 | 5.00 |
| [`gpt-6-luna`](https://developers.openai.com/api/docs/models/gpt-6-luna) | 0.125 | 0.25 |

The adapter already retains reported cache-write counts. Cost accounting now
prices those counts and the no-spend budget includes the possible write
premium, 1.25 times the applicable input rate. Cache writes count toward the
full request's 272k threshold. GPT-6.1 Sol's write rates remain as below.
GPT-5.6 Sol's current offer lasts at least through November 21; no later
rate is published, so no later transition is invented.

### GPT-6.1 Sol pricing and request limits

The [official model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
was rechecked on 2026-10-26. Standard synchronous USD rates per million tokens:

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
was rechecked on 2026-10-26: $1.40 input, $0.26 cached input and $4.40 output
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

The [dated comparison](observed-model-comparison.md) now includes native Z.ai
GLM-5.3, Flash and FlashX observations from October 29: each passed 7/8 cases.
The invoice-label or raw-JSON contract failures remain visible. Historical
OpenRouter/Relace measurements retain that host's separate route and prices.

Native Z.ai catalogue discovery is not implemented. Enter `glm-5.3` explicitly
for native runs, or discover `z-ai/glm-5.3` through OpenRouter using its live
route prices. A successful discovery is not an access or compatibility probe.

## Gaps vs this documentation version

These IDs are **not** in the snapshot table because they are not public
first-party routes we can price honestly:

| Gap | Status as of 2.21.0 |
|---|---|
| Kimi (Moonshot) native provider | Call via OpenRouter or `openai_compatible`. |
| Z.ai native catalogue | Native `glm-5.3` chat is supported; discovery uses OpenRouter or explicit model entries. |
| TypeSafe Jev as a chat model | Catalogue-visible typed-decision route only. |

The [GitHub Marketplace Action guide](../automation/github-action.md) shows
how to use a published package with its release-tag Action. Pages
with an older **As of** stamp still describe their stated version; they were
not all re-reviewed for 2.21.0.

See the [model catalogue](model-catalog.md) for discover → probe → smoke, and
[`examples/frontier-candidates.json`](../../examples/frontier-candidates.json)
for a current flagship example set.
