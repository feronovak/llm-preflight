# Direct GLM, DeepSeek and Qwen checks

**Last reviewed:** 2026-10-15 · **As of:** v2.21.2

These direct routes bypass OpenRouter. Their deterministic protocol fixtures
pass. The [dated comparison](observed-model-comparison.md) distinguishes native
and routed observations; those observations apply to their recorded date and
route. DeepSeek's current Flash alias changed after the October 14 observation.
The unpublished 2.23.0 build adds GLM Flash/FlashX and further native providers;
see [current native checks](native-providers.md) for their fixture-only status.

| Model | Provider | Native API model ID | Credential |
|---|---|---|---|
| GLM 5.3 | `zai` | `glm-5.3` | `ZAI_API_KEY` |
| DeepSeek V4.1 Flash | `deepseek` | `deepseek-flash` | `DEEPSEEK_API_KEY` |
| Qwen 3.8 Max | `qwen` | `qwen3.8-max` | `DASHSCOPE_API_KEY` |

Z.ai uses its dedicated adapter at `https://api.z.ai/api/paas/v4`.
DeepSeek uses the shared OpenAI-compatible adapter at
`https://api.deepseek.com/v1`. Qwen uses the same wire protocol with a
Model Studio endpoint and native credentials. Sharing an adapter does not
send traffic through OpenRouter.

## Configure the actual account

Copy [the three-model smoke example](../../examples/native-chinese-smoke.json)
to `native-smoke.json` in your project. Put the native keys in your shell or
`.env.production` beside that copy. An OpenRouter key cannot authenticate
these routes.

For Qwen, set the model's `base_url` to the endpoint shown by your Model Studio
workspace. Current [Alibaba documentation](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)
uses workspace-scoped URLs, for example
`https://WORKSPACE_ID.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`
for Singapore. Replace `WORKSPACE_ID`; other regions use different hosts.
The package's legacy international default remains available for accounts
that use it. Confirm the account endpoint before a live run.

The example's Qwen override records Singapore/International list prices.
Review the account's region and deployment scope against
[Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing).
Its cache-hit rate is deliberately `null`: Alibaba directs Qwen 3.8 cache
prices to the account console. Copy the reviewed rate into
`cached_input_cost_per_million` in your local configuration before relying on
cache-hit cost figures. Otherwise cached requests retain unknown cost;
neither OpenRouter nor QwenCloud cache rates are substituted.

## Validate locally first

```bash
llm-preflight native-smoke.json --contract-check --json
llm-preflight native-smoke.json --doctor --json
llm-preflight native-smoke.json --pricing-check --json
llm-preflight native-smoke.json --dry-run --json
```

These commands do not generate model responses. Missing keys fail doctor;
expired review dates fail strict price checks. Confirm the selected endpoint,
prices and three-request plan before approving live execution.

The example uses one request per model, no retries or warmups, low reasoning,
a 4,096-token combined output setting and a $0.10 estimated-cost cap. It sets
Qwen's `max_tokens_parameter` explicitly to `max_completion_tokens`, so that
setting also works with installed 2.21.2. The automatic Qwen default correction
ships in 2.22.0.
In that release, planner, doctor and transport also reject overrides of
model, messages, streaming and token-limit fields in provider options for all
three native routes. Set `request.max_output_tokens` instead. A legacy
`max_tokens` model parameter is accepted only with explicitly disabled thinking.

[GLM 5.3](https://docs.z.ai/guides/llm/glm-5.3) requires reasoning enabled.
[DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/) names V4.1 Flash
`deepseek-flash`. Native Model Studio uses `enable_thinking` and
`reasoning_effort`; OpenRouter's `reasoning.enabled` field is a different
request format. The earlier routed Qwen rejection does not establish whether
the native request will work for your account.

Provider limits and token-based estimates are not an invoice guarantee;
Alibaba documents possible overrun of the combined limit by up to ten tokens.
A successful synthetic protocol fixture is not a live model result. Keep new
native observations separate from the [recorded routed comparison](observed-model-comparison.md).
