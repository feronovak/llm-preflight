# Check current native models

**Last reviewed:** 2026-10-26 · **As of:** v2.23.0

The unpublished 2.23.0 source build adds native Kimi, MiniMax, Mistral and
Cohere text routes, GPT-6.1 Terra pricing, GLM Flash siblings and restricted
Mythos pricing. Install the candidate wheel or the source checkout to use
these additions. The published 2.22.2 package does not contain them.

The [October 29 comparison](observed-model-comparison.md) now supplies live
observations for 19 native routes, including Terra, Kimi K3.1 Pro and GLM Flash/FlashX.
It does not establish native MiniMax, Mistral or Cohere access; their keys were
unavailable. Restricted Mythos and Kimi Highspeed were not accessible in the
preceding smoke, so neither appears as a successful measurement.

Use a local contract to define the response your application needs, then
preview the actual provider request and estimated cost. Passing local fixtures
verifies the validator. It does not measure a model, run your application's
parser or grant approval for a live request.

## Choose the route and example

| Provider | Model ID | Default credential | Bounded source example |
|---|---|---|---|
| `openai` | `gpt-6.1-terra` | `OPENAI_API_KEY` | [Terra](../../examples/gpt-6.1-terra.json) |
| `zai` | `glm-5.3-flash` | `ZAI_API_KEY` | [GLM Flash](../../examples/glm-5.3-flash.json) |
| `zai` | `glm-5.3-flashx` | `ZAI_API_KEY` | [GLM FlashX](../../examples/glm-5.3-flashx.json) |
| `moonshot` | `kimi-k3.1-pro` | `MOONSHOT_API_KEY` | [Kimi Pro](../../examples/kimi-k3.1-pro.json) |
| `moonshot` | `kimi-k3.1-pro-highspeed` | `MOONSHOT_API_KEY` | [Kimi Highspeed](../../examples/kimi-k3.1-pro-highspeed.json) |
| `minimax` | `MiniMax-M3.1-Flash` | `MINIMAX_API_KEY` | [MiniMax Flash](../../examples/minimax-m3.1-flash.json) |
| `minimax` | `MiniMax-M3` | `MINIMAX_API_KEY` | [MiniMax M3](../../examples/minimax-m3.json) |
| `mistral` | `mistral-large-4` | `MISTRAL_API_KEY` | [Mistral Large 4](../../examples/mistral-large-4.json) |
| `cohere` | `command-a-plus-05-2026` | `COHERE_API_KEY` | [Cohere Command A+](../../examples/cohere-command-a-plus.json) |
| `anthropic` | `claude-mythos-5-1` | `ANTHROPIC_API_KEY` | [Restricted Mythos](../../examples/mythos-5.1-restricted.json) |

Model IDs are case-sensitive. The `moonshot` provider names Kimi's native API;
it uses `https://api.moonshot.ai/v1`. MiniMax uses `https://api.minimax.io/v1`,
Mistral uses `https://api.mistral.ai/v1`, and Cohere uses
`https://api.cohere.com/v2`. Each route authenticates with its own environment
variable. Provider credentials and output caps never come from discovery.

## Run the checks without spending

From the source checkout, with the candidate package installed, run:

```bash
llm-preflight examples/kimi-k3.1-pro.json --contract-check --json --no-env-file
llm-preflight examples/kimi-k3.1-pro.json --pricing-check --json --no-env-file
llm-preflight examples/kimi-k3.1-pro.json --dry-run --json --no-env-file
```

Substitute any example from the table. Each contains an accepted `billing`
fixture and a rejected `sales` fixture, one request, no warmup, one attempt,
4,096 output tokens and a $0.50 estimated-cost ceiling. The ceiling is a limit,
not the expected cost or permission to spend. Review the model, prompt, output
allowance and pricing before any live run. Reasoning can exhaust a small output
allowance; a local fixture cannot establish that a model will return the answer.

Copy an example into your project and replace its routing contract with the
actual response rules your consumer enforces. Add positive and negative cases
for every advertised prompt. Run `--doctor` when ready to check credentials;
the three commands above do not need a key or contact the provider.

## Request and price limits

- Terra's example uses Responses with the configured low reasoning effort.
  This adapter forwards `reasoning`, `text`, `service_tier`,
  `prompt_cache_retention` and `prompt_cache_key`; it refuses other provider
  options before planning. GPT-6 Responses results require `status: completed`;
  incomplete or malformed output is a failed request.
  The official GPT-6 endpoint/settings govern
  tool calling; this tool validates canonical definitions locally and does not
  execute tools or computer-use workflows. GPT-6 Fast/Ultrafast and non-30-minute
  cache-retention settings are refused by this pricing path.
- Kimi K3.1 always reasons. Use `low`, `high` or `max`; its fixed sampling
  settings are omitted. The snapshot covers implicit caching with the default
  five-minute write retention. Other retention settings require a separately
  supported pricing path; this native path refuses them. Highspeed has its own
  input/output/write rates and shares the published $0.20 cache-read rate.
- MiniMax uses `max_completion_tokens` to bound reasoning plus answer, with
  reasoning separated from answer text. M3.1 Flash requires adaptive thinking;
  M3 also accepts disabled thinking. Priority billing is outside the standard
  snapshot path. M3's input/cache/output rates double above 512,000 input tokens.
- Mistral Large 4 is a public-preview model. Both `mistral-large-4` and
  `mistral-large-4-0` have reviewed prices. The adapter checks complete text
  streams, extracts final text from typed reasoning/text blocks, and accepts
  documented cached-usage field variants. Reasoning remains in billable usage.
- Cohere's adapter uses v2 Chat and bills from `usage.billed_units`, not the
  larger count that can include provider-injected tokens. Its public Command A+
  API is documented as free within rate limits. Model Vault, private deployments
  and commercial agreements require their own reviewed configuration and prices.
  A free price does not establish access, and absent usage remains unknown cost.
- GLM Flash/FlashX thinking cannot be disabled. GLM-5.3 remains text-only in its
  existing route. The newly added Kimi, MiniMax, Mistral and Cohere adapters
  currently accept text inputs only; model vision capabilities do not imply
  this adapter validates image contracts.
- Mythos 5.1 requires verified access and the provider's applicable retention
  arrangement. It shares Fable 5.1's published rates. Both require adaptive
  thinking and reject forced tool choice. A price row does not establish account
  eligibility or zero-data-retention availability.

The new native text adapters reject truncated streams, output-limit stops,
provider error events and malformed text. Missing usage remains unavailable
cost even when text arrives. Provider options cannot replace the model,
messages, stream settings or output cap that the planner reviewed.

Bundled prices apply to the documented public base URL. A different deployment
leaves official pricing unknown, including saved official rows. Explicit
reviewed owner prices take precedence. Qwen cache prices and regional deployment
differences retain their documented limitations; OpenRouter prices remain tied
to the routed host. See [current snapshots](current-snapshots.md).

## Discovery and other entry points

`catalog init` includes Kimi, MiniMax, Mistral and Cohere metadata sources.
Their metadata is a candidate for review, not a successful probe or approval.
Cohere discovery filters Chat models and follows bounded pagination. Z.ai uses
configured native models; no metadata discovery endpoint is integrated.

| Surface | Coverage in the source build |
|---|---|
| CLI checks and plans | Native settings, route-specific pricing and existing three-state decisions. |
| Source audit and change plans | New literal model families and explicit provider prefixes; an explicit OpenRouter route does not inherit native prices. Literal scanning does not resolve an application's dynamic endpoint or execute its parser. |
| MCP | Existing contract, pricing and plan tools reuse native validation. Read-only tools accept configured models and refuse provider discovery. Live calls retain explicit confirmation requirements. |
| Saved results and reports | Existing normalized usage, observed model identity, cost coverage and decision fields; no new live result is implied by fixtures. |
| GitHub Action | Runs the installed package. Published defaults remain 2.22.2 until release; new providers require the candidate package or the published 2.23.0 after publication. |
| Agent plugin | Existing guidance requires reporting the contract, price/plan decision, warnings and unknown evidence before any live work. |

DeepSeek's `deepseek-flash` currently resolves to V4.1-Flash-1017. Its legacy
`deepseek-v4-flash` and `deepseek-v4-flash-vision-exp` IDs redirect to that model
at Flash prices. The image/text fixture verifies transport and retained observed
identity; it does not renew an older observation of the alias. Pre-run image
cost remains unavailable. TypeSafe Jev 1.14 is updated for catalog pricing only
and remains incompatible with a text smoke.

Provider specifications and prices: [Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra),
[Kimi](https://platform.kimi.ai/docs/api/chat),
[MiniMax](https://platform.minimax.io/docs/api-reference/text-chat-openai),
[Mistral](https://docs.mistral.ai/models/mistral-large-4-0),
[Cohere](https://docs.cohere.com/docs/command-a-plus),
[GLM Flash](https://docs.z.ai/guides/vlm/glm-5.3-flash),
[Fable/Mythos](https://platform.claude.com/docs/en/models/fable-5-1/overview),
[DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/).
