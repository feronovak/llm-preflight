# Configuration

**Last reviewed:** 2026-10-19 · **As of:** v2.22.1

## Models and providers

Every `models` entry has the same basic shape. Replace `provider-model-id`
with the exact reviewed ID your application uses:

```json
{
  "name": "label-in-reports",
  "provider": "openai",
  "model": "provider-model-id"
}
```

| Provider | Default API key variable |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `gemini` | `GEMINI_API_KEY` |
| `xai` | `XAI_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY` |
| `deepseek` | `DEEPSEEK_API_KEY` |
| `qwen` | `DASHSCOPE_API_KEY` |
| `zai` | `ZAI_API_KEY` |
| `moonshot` | `MOONSHOT_API_KEY` |
| `minimax` | `MINIMAX_API_KEY` |
| `mistral` | `MISTRAL_API_KEY` |
| `cohere` | `COHERE_API_KEY` |
| `typesafe` | `TYPESAFE_API_KEY` |
| `openai_compatible` | configured with `api_key_env` |

The unpublished 2.23.0 source build adds the `moonshot`, `minimax`, `mistral`
and `cohere` rows. Their current native adapters support text only. See
[native provider checks](../guides/native-providers.md) for exact IDs,
reasoning settings, public endpoint scope and bounded source examples.

`typesafe` discovers Jev for catalogue review. Jev returns typed decisions
rather than generated text, so it is not eligible for a generic text smoke.
Use `qwen` for Alibaba Model Studio's OpenAI-compatible chat route. The
default endpoint is the international compatible-mode URL, which matches the
bundled USD snapshots. A China Beijing endpoint remains valid by setting
`base_url`; the checked-in Qwen-VL example does that. Bundled public-route
prices do not apply to a different endpoint; supply reviewed deployment prices
when a cost gate requires them. The existing
`openai_compatible` plus `DASHSCOPE_API_KEY` form also remains valid.
For account-specific Qwen endpoints, reasoning limits and a bounded native
smoke, see [direct GLM, DeepSeek and Qwen checks](../guides/native-chinese-models.md).

Use `zai` for GLM-5.3 on the standard Z.ai Chat Completion endpoint,
`https://api.z.ai/api/paas/v4`. Its native price snapshot does not apply to
Coding Plan quotas or OpenRouter's `z-ai/glm-5.3` route. Reasoning is always
enabled; select `low`, `high`, or `max` through
`request.provider_options.zai.reasoning_effort`. The native adapter rejects
unsupported efforts and image inputs for this text-only model.

Override endpoint and authentication details with `base_url`, `api_key_env`,
and `headers`. Use `provider_options` inside `request` only when normalized
settings such as temperature, system prompt, and output limit are insufficient.

For normal benchmarks, enter only the provider and model ID you intend to use.
Do not copy catalogue internals such as `catalog_type`, `catalog_confidence`,
or `adapter` into your JSON. The catalogue workflow discovers those details and
keeps its compatibility evidence under `benchmarks/.llm-preflight/` automatically.

Bundled prices are resolved when available. An unlisted model stays unpriced
until reviewed rate evidence is supplied; do not copy zero prices into a live
model merely to silence a warning. See [pricing and safety](../guides/pricing-and-safety.md).

## Reuse an existing project env file

Set a config-relative `env_file` to reference an existing local file without
copying credentials. The reference cannot escape the configuration directory;
shell values still take precedence. `--env-file PATH` explicitly overrides it,
and `--no-env-file` disables all env-file loading. `--doctor --json` reports
credential provenance as `shell`, `env_file`, or `missing`, plus the selected
file status: `present`, `missing_file`, or `not_checked` when file loading was
disabled. It never prints credential values.

```json
{
  "env_file": "credentials/team.env",
  "models": [{"provider": "openai", "model": "gpt-5.4-mini", "api_key_env": "TEAM_OPENAI_KEY"}]
}
```

### OpenAI-compatible endpoints

For vLLM, LiteLLM, a hosted Ollama service, or another OpenAI-style proxy, use
the `openai_compatible` provider and supply its endpoint explicitly. Keep a
key in an environment variable when the proxy requires one.

```json
{
  "prompt": "Reply with exactly: ok",
  "models": [{
    "name": "local-llama",
    "provider": "openai_compatible",
    "model": "llama3.1",
    "base_url": "https://llm.example.com/v1"
  }],
  "validation": {"exact": "ok"},
  "warmups": 0,
  "repetitions": 1
}
```

If the endpoint needs a key, add `"api_key_env": "PROXY_API_KEY"` and set it
in `.env.production` or your shell. The endpoint must be an HTTP(S) URL on a
public host and is checked before requests are made; direct loopback and private
network endpoints are intentionally rejected.

## Image-to-text input fixtures

Use `request.input_images` to preflight an existing text or JSON response
contract that depends on a supplied image. This checks the integration shape;
it does not rate image quality, prompt faithfulness, or models.

```json
{
  "prompt": "Read the order number and return JSON.",
  "request": {
    "input_images": [
      {"path": "fixtures/order.png", "mime_type": "image/png"}
    ],
    "max_output_tokens": 100
  },
  "models": [{
    "name": "qwen-vl",
    "provider": "openai_compatible",
    "model": "qwen3-vl-plus",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key_env": "DASHSCOPE_API_KEY"
  }],
  "validation": {
    "json_schema": {
      "type": "object",
      "required": ["order_number"],
      "properties": {"order_number": {"type": "string"}}
    }
  }
}
```

The path must be relative to the config and cannot escape its directory. PNG,
JPEG, WEBP, and GIF inputs are supported up to 10 MiB and 20 million pixels.
The declared MIME type must match the file header. LLM Preflight stores a
content hash and dimensions, never image bytes, in results. OpenRouter and
OpenAI-compatible chat routes receive OpenAI multipart image content; Gemini
receives inline image data. Unsupported adapters fail rather than ignoring an
image. The pre-run cost plan reports image-input cost as unavailable because
providers meter images differently; completed runs use provider-reported token
usage when it is available. See [image-to-text contract inputs](../guides/vision-inputs.md)
for the integration boundaries.

## Custom prompts

Custom prompts are named, reusable tests:

```json
{
  "prompts": [{
    "name": "csv-review",
    "system_prompt": "Return concise JSON.",
    "prompt": "Find invalid rows in this CSV:\\norder_id,total\\nA-1,20\\nA-2,-5",
    "request": {"temperature": 0, "max_output_tokens": 500},
    "validation": {"contains": "A-2"}
  }]
}
```

**Paid requests:** the following commands can contact every selected provider.
Preview each selection with `--dry-run` and authorize its bounds first.

```bash
llm-preflight benchmark.json --prompt csv-review
llm-preflight benchmark.json --tests exact-routing-check,csv-review
```

For long content, use `prompt_file` relative to the config file. It must remain
inside that directory; `..` paths are rejected. Use `prompt` or `prompt_file`,
not both, and do not commit sensitive fixture data.

For a migration-focused tutorial and runnable JSON, routing, and content-rule
examples, see [Custom contract tests](../guides/output-contracts.md).

## Contract fixtures

`validation_fixtures` lists responses that the configured validator must accept
or reject, so `--contract-check` can prove the rule locally before any paid
request. Each fixture has exactly `name`, `response`, and `expect` (`pass` or
`fail`), and a list needs at least one of each.

Fixtures live at the same level as the `validation` they test. For a single
top-level `prompt`, put them at the top level beside `validation`. For a custom
prompt in `prompts`, put them inside that prompt beside its `validation`:

```json
{
  "prompts": [{
    "name": "routing",
    "prompt": "I was charged twice for the same subscription.",
    "validation": {"exact": "billing"},
    "validation_fixtures": [
      {"name": "expected queue", "response": "billing", "expect": "pass"},
      {"name": "wrong queue", "response": "technical", "expect": "fail"}
    ]
  }]
}
```

A fixture list without a `validation` at its own level is a configuration
error, because there would be no rule to test. `--contract-check` reports
top-level fixtures first and then each prompt's fixtures by prompt name. A
benchmark refuses to start before provider work when any configured fixture
disagrees with its validator.

## Presets, aliases, and environments

Presets translate intent into provider-aware options. Available presets are
`json`, `no-reasoning`, `low-latency`, and `structured`. Explicit request
values win over top-level and prompt preset defaults. A config with neither `request` nor `presets` sends temperature 0 and 256 output tokens; with presets and no `request`, presets expand onto an empty request, so temperature is the provider default unless a preset such as `low-latency` sets it. A prompt preset fills only keys left unset, under both `--prompt` and `--tests`. A prompt `provider_options` object replaces that dict; top-level presets then fill only the defaults that object left unset. A built-in test runs the same every time: its own presets expand into its own request, which replaces those keys of the run request, a `provider_options` object as a whole. So `strict-json-extraction` sends temperature 0, 256 output tokens and reasoning off whatever the run request sets.

All native providers use a safe default output limit of 256 tokens when neither
`max_output_tokens` nor `max_tokens` is set. Set an explicit limit for tasks
that need longer responses; this makes cost comparisons intentional and fair.

### Structured contracts by provider

Use the same JSON Schema contract for every candidate model, but keep the
acceptance boundary aligned with the application that consumes its response.

| Provider family | `structured` preset behavior | Contract guidance |
|---|---|---|
| OpenAI / Codex models | Requests `json_object` response format. | Keep raw JSON validation unless the deployed parser deliberately accepts fenced JSON. |
| Claude | Uses the prompt and validator; no Anthropic-specific JSON field is forced. | Use `json_schema` plus a clear JSON-only instruction. Set `allow_fenced_json` only when the deployed parser accepts one fenced block. |
| Gemini | Requests `application/json` MIME output and suppresses returned thoughts. | Keep the schema strict and inspect failed responses for safety or format changes. |

For a low-cost, production-shaped functional check, select the recommended
suite with `--tests agent-smoke --smoke`. It covers strict JSON extraction,
support classification, a code-patch summary, a source-grounded quiz, and a
privacy boundary. It deliberately excludes the opt-in `load` concurrency
profile.

```json
{
  "aliases": {"fast": {"provider": "openai", "model": "gpt-5.4-mini"}},
  "environments": {
    "ci": {"repetitions": 1, "warmups": 0},
    "deep": {"profiles": "all", "suite_repetitions": 20}
  },
  "models": ["fast"]
}
```

Run an overlay with `llm-preflight benchmark.json --env ci`. See
[tests, pricing, and safety](../guides/pricing-and-safety.md) for validation choices and
data handling. See the [complete configuration reference](configuration-schema.md)
for every supported key and default.

### Responses request options in the 2.23.0 source build

With `provider: openai` and `adapter: openai_responses`, the supported
`request.provider_options.openai` fields are `reasoning`, `text`, `service_tier`,
`prompt_cache_retention` and `prompt_cache_key`. The adapter forwards these
fields to Responses. Other fields are refused before planning; set the prompt,
system prompt and output allowance through the normal configuration fields.
The adapter uses `store: false`. GPT-6 pricing still requires standard service
and30-minute cache retention. GPT-6 Responses require completed response status;
partial text from an incomplete or failed response cannot count as a success.
