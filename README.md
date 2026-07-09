# LLM Speed Bench

A dependency-free Python CLI for repeatable benchmarks across OpenAI, Anthropic,
Gemini, xAI/Grok, OpenRouter, and arbitrary OpenAI-compatible APIs. It uses each
provider's streaming API and retains raw samples in JSON, allowing runs to be
compared as providers and models change.

> [!WARNING]
> Benchmarks make paid API requests. Preview the catalog first, keep limits and
> repetitions small while configuring a run, and review the interactive
> confirmation before proceeding.

## What it measures

- End-to-end request latency (p50 and p95)
- Time to first generated token (TTFT)
- Output tokens per second, when the provider reports token usage
- Success/error rate and response validation failures
- Input/output token totals and estimated cost, when pricing is configured
- Reproducibility metadata: exact request settings, prompt hash, time, host, and
  raw per-request observations

Network distance, provider load, rate limits, and concurrency affect these
numbers. Run from the same host and use at least 20 measured repetitions for
meaningful comparisons. The default concurrency of one measures interactive
latency; create a separate configuration with higher concurrency to measure load
behavior.

## Quick start

Python 3.10 or newer is required. No runtime packages are needed.

```bash
cp benchmark.example.json benchmark.json
cp .env.example .env.production
# Edit benchmark.json and add only the provider keys you use.
python3 -m llm_bench.cli benchmark.json
```

Alternatively, put the keys in `.env.production` next to the benchmark
configuration. The CLI loads that file automatically and does not overwrite
variables already present in the environment:

```dotenv
OPENAI_API_KEY="..."
ANTHROPIC_API_KEY="..."
GEMINI_API_KEY="..."
OPENROUTER_API_KEY="..."
XAI_API_KEY="..."
```

Or install the local CLI:

```bash
python3 -m pip install -e ".[dev]"
llm-bench benchmark.json
```

Each run prints an aligned terminal table and writes full JSON plus a Markdown
report under `results/`. Interactive terminals use color for successful,
partial, and failed rows. Commit or archive the result files if you want durable
trend history. The report ends with an executive summary naming the fastest
model, the cheapest model, and the best value. Value equally weights
valid-output reliability, relative speed, and relative measured cost. Failed
models are excluded from cheapest/value rankings. New result files also record
warmup usage and total estimated spend for the complete run.

## Automatic model discovery

Use `discovery` to resolve models from provider catalogs at run time. Every
source requires a positive `limit`; this is a cost-safety control. Optional
`include` and `exclude` values are case-insensitive regular expressions.

```json
{
  "discovery": [
    {
      "provider": "openrouter",
      "sort": "newest",
      "output_modalities": "text",
      "limit": 5
    }
  ]
}
```

Inspect exactly what would run without making generation requests:

```bash
python3 -m llm_bench.cli benchmark.auto.example.json --catalog
```

Choose models, providers or provider families, test profiles, and repetitions
interactively. The CLI shows a summary and requires confirmation before making
generation requests. During the run it reports the current model and request,
profile/case, success or error status, input/output tokens, and estimated cost:

```bash
python3 -m llm_bench.cli benchmark.auto.example.json --interactive
```

Model selections accept numbers, a provider such as `openai`, or a provider
family such as `openrouter/qwen`. Multiple selections are comma-separated.

Then benchmark the dynamically selected set:

```bash
python3 -m llm_bench.cli benchmark.auto.example.json
```

Run the complete mixed benchmark suite:

```bash
python3 -m llm_bench.cli benchmark.auto.example.json --profiles all
```

Or select a subset:

```bash
python3 -m llm_bench.cli benchmark.auto.example.json \
  --profiles chat-fast,classification,reasoning
```

The built-in profiles are `chat-fast`, `classification`,
`structured-extraction`, `reasoning`, and `load`. The load profile runs at
concurrency 1, 5, and 10. Coding is intentionally excluded. Set
`"profiles": "all"` in the configuration to make the mixed suite the default,
and use `"suite_repetitions"` to repeat each deterministic case.

The catalog response is snapshotted into each result. Gemini discovery records
token limits, supported methods, and its thinking flag. OpenRouter records
pricing, context, modalities, tool/structured-output support, and reasoning
support. OpenAI and Anthropic discovery records the catalog data those APIs
actually return; missing capabilities remain `null` rather than being guessed.
Explicit `models` and discovered models can be used together.

## Development

The repository follows a strict red/green/refactor workflow:

1. Write a focused test for the next behavior.
2. Run it and confirm the expected failure.
3. Add the smallest implementation that makes it pass.
4. Run the entire suite.
5. Refactor only while the suite remains green.

```bash
# Focused red/green cycle
make test-one TEST=tests/test_catalog.py::test_openrouter_normalization_and_limit

# Complete verification
make test
make coverage
```

See `AGENTS.md` for the durable development contract. Live provider credentials
are not needed by the deterministic unit tests.

## Providers and configuration

Every entry in `models` uses the same interface:

```json
{
  "name": "label-in-reports",
  "provider": "openai",
  "model": "provider-model-id",
  "input_cost_per_million": 0,
  "output_cost_per_million": 0
}
```

Supported provider values and default credentials:

| Provider | Native interface | Default API key variable |
|---|---|---|
| `openai` | OpenAI chat completions | `OPENAI_API_KEY` |
| `anthropic` | Anthropic messages | `ANTHROPIC_API_KEY` |
| `gemini` | Gemini generate content | `GEMINI_API_KEY` |
| `xai` | xAI OpenAI-compatible chat completions | `XAI_API_KEY` |
| `openrouter` | OpenAI-compatible chat completions | `OPENROUTER_API_KEY` |
| `openai_compatible` | Configurable chat completions URL | configured with `api_key_env` |

Provider defaults can be overridden per model using `base_url`, `api_key_env`,
and `headers`. This supports proxies, regional gateways, local inference servers,
and OpenRouter attribution headers. `provider_options` inside the shared
`request` object passes provider-specific body fields when the normalized
`temperature`, `system_prompt`, and `max_output_tokens` settings are insufficient.

Native Grok configuration:

```json
{
  "provider": "xai",
  "model": "grok-4.3"
}
```

Native xAI discovery uses the same filtering and mandatory limit controls:

```json
{
  "provider": "xai",
  "include": "^grok-",
  "limit": 5
}
```

Secrets are read only from environment variables. Custom headers are removed
from catalog output and are not included in benchmark results. Provider errors,
prompts, model metadata, and optionally full responses can still contain
sensitive information, so review result files before sharing them.

To add a protocol that is not OpenAI-compatible, implement `ProviderClient` and
register it in `create_client` in `llm_bench/client.py`. The benchmark runner,
validation, metrics, and output format need no changes.

## Fair comparison checklist

- Keep the prompt, system instructions, temperature, and maximum output fixed.
- Compare the prompt hash and request settings in result files.
- Use validation so fast but empty or malformed responses count as failures.
- Separate cold/warm and single-user/load tests; do not mix their histories.
- Pin dated model IDs when providers offer them. Aliases may silently change.
- Treat provider token counts as authoritative; character-based approximations
  are deliberately not used.

## Pricing

OpenRouter prices are taken from its live model catalog. Public standard API
rates for selected OpenAI, Gemini, and Anthropic models are maintained in
`llm_bench/pricing.py` with an `as_of` date. Provider pricing changes over time;
verify rates before relying on cost comparisons. Explicit
`input_cost_per_million` and `output_cost_per_million` values in a model
configuration override the registry.

Estimated spend includes measured requests and warmups. It does not include
provider-specific taxes, volume agreements, data-residency premiums, tool-call
fees, cache discounts, or other account-specific adjustments.

## Security

- Never commit `.env.production`, backup environment files, raw results, or
  debug logs.
- Use synthetic prompts for public benchmarks.
- Treat `results/` as sensitive when `save_responses` is enabled.
- Rotate any credential that appears in Git history or logs.
- See [SECURITY.md](SECURITY.md) for private vulnerability reporting.

## Project structure

```text
llm_bench/                  CLI, providers, discovery, profiles, metrics
tests/                      deterministic unit tests
benchmark.example.json      explicit-model configuration example
benchmark.auto.example.json discovery and profile configuration example
.env.example                credential variable template
```

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md) for the test-driven workflow. This
project is available under the [MIT License](LICENSE).
