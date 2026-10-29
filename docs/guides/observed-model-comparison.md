# Observed model comparison: support-routing example

**Last reviewed:** 2026-10-29 · **As of:** v2.23.0

**Latest measurement:** 2026-10-29, 19 native model IDs, eight cases each.
The previous 12-model run and earlier tables retain their original dates and
routes below. API rejection, rate limits and contract failures are separate
observations. These repository-owned synthetic cases are not confirmed
production traffic, a universal ranking or production approval.

## 2026-10-29 bounded comparison

The owner-approved run used the unpublished **2.23.0 source build**, the same
eight support-routing and strict JSON cases once per model, no warmups, and
one attempt per request. All models used a **1,024-token output allowance** and
low reasoning effort where supported. Requests within each model were sequential;
up to four provider blocks could overlap on the same host. All routes were native.

All **152** planned calls were attempted: **147** returned API responses,
**144** passed validation, **three** failed the output contract, and **five**
returned API errors. **15 of 19 models passed 8/8 checks.** No automatic retries,
provider fallback, alternative routes or additional paid probes were made.

| Provider route | Exact API model ID | Checks passed / 8 | API successes / 8 | Mean latency | Estimated cost / 8 |
|---|---|---:|---:|---:|---:|
| OpenAI | `gpt-6-astra` | 8/8 | 8/8 | 2.089s | $0.010580 |
| OpenAI | `gpt-6.1-sol` | 8/8 | 8/8 | 1.476s | $0.002116 |
| OpenAI | `gpt-6.1-terra` | 8/8 | 8/8 | 1.192s | $0.001218 |
| OpenAI | `gpt-6-luna` | 8/8 | 8/8 | 1.205s | $0.000174 |
| Anthropic | `claude-fable-5-1` | 8/8 | 8/8 | 0.923s | $0.014500 |
| Anthropic | `claude-opus-5-5` | 8/8 | 8/8 | 1.497s | $0.005740 |
| Anthropic | `claude-sonnet-5-5` | 8/8 | 8/8 | 1.421s | $0.002870 |
| Anthropic | `claude-haiku-5-5` | 8/8 | 8/8 | 1.758s | $0.000150 |
| Gemini | `gemini-4-argon` | 8/8 | 8/8 | 5.186s | $0.002728 |
| Gemini | `gemini-3.8-flash` | 8/8 | 8/8 | 2.621s | $0.002723 |
| Gemini | `gemini-3.6-flash` | 8/8 | 8/8 | 1.359s | $0.004005 |
| xAI | `grok-4.7` | 8/8 | 8/8 | 1.567s | $0.007536 |
| DeepSeek | `deepseek-flash` | 8/8 | 8/8 | 1.297s | $0.000809 |
| DeepSeek | `deepseek-v4-pro` | 8/8 | 8/8 | 1.766s | $0.004220 |
| Alibaba Singapore | `qwen3.8-max` | 8/8 | 8/8 | 3.834s | $0.006034 |
| Z.ai | `glm-5.3` | 7/8 | 8/8 | 1.461s | $0.001398 |
| Z.ai | `glm-5.3-flash` | 7/8 | 8/8 | 1.832s | $0.000162 |
| Z.ai | `glm-5.3-flashx` | 7/8 | 8/8 | 1.091s | $0.000391 |
| Moonshot/Kimi | `kimi-k3.1-pro` | 3/8 | 3/8 | 2.217s | — |

The [machine-readable aggregates](../data/model-comparison-2026-10-29.json)
retain all 19 rows, request settings, reported identities, token/cost coverage,
case and private-result hashes. The known token-cost subtotal is **$0.06902127**
across **147** calls with usage. **Total cost remains unknown** because the five
API errors supplied no usage. Kimi's partial known cost is retained in the JSON;
its full eight-call cost stays unavailable in the table and image. API errors
are not assumed free. The approved maximum token-based estimate was **$1.64**,
not an invoice guarantee. Earlier smoke checks are separate evidence and are
not included in these 152 calls or this subtotal.

### Failures and interpretation

- **GLM-5.3:** seven checks passed. The invoice-request response selected
  `account`; the unchanged case required `billing`. Valid JSON alone did not
  satisfy the application contract.
- **GLM-5.3 Flash and FlashX:** each passed seven checks. Their ticket-extraction
  output included Markdown JSON fences; the unchanged consumer contract required
  raw JSON. Both were rejected rather than silently stripping the fences.
- **Kimi K3.1 Pro:** the first three label checks passed. The other five calls
  returned HTTP 429 (`rate_limit_reached_error`), so those JSON tasks have no
  model-quality result. No retries were made.
- **The other 15 models:** all eight API calls and validators passed for this
  synthetic workload. This is scoped evidence, not production approval.

All three retained invalid outputs were replayed locally against the unchanged
validators and failed again. Full response fields were retained for failures
only; bounded previews and per-request flags can remain for passing calls.
Public aggregates contain no response text, API keys, account identifiers or
local paths. Private raw evidence is excluded from the public repository and
package artifacts.

### Request settings and comparability

The eight cases cover billing, technical and account labels; strict ticket
extraction; duplicate-charge prompt injection; an active technical outage;
account email changes; and an invoice request. Each case has a positive and
negative local validator fixture in the
[reusable comparison configuration](../../examples/current-model-comparison.json).
The aggregate case fingerprint binds those exact prompts, schemas and fixtures.

OpenAI uses Responses with `store: false` and low reasoning effort. Claude uses
low output effort and its documented adaptive-thinking behavior. Gemini uses
`LOW` thinking; Grok, DeepSeek, Qwen, GLM and Kimi use their supported low-effort
settings. Qwen caps reasoning and answer together with `max_completion_tokens`.
Temperature is omitted. Reported reasoning tokens remain billable usage even
when reasoning text is excluded from validation. Cache usage follows each row's
recorded native-route price evidence; cache-hit rates were not systematically
tested. Mean latency includes API successes, including contract failures, and
excludes API errors.

This run replaces the previous measurement in the README and current summaries.
The October 14 run and earlier measurements remain below as history. They used
different routes, two repetitions, and different output allowances, so these
figures do not establish a like-for-like improvement or a general model ranking.
A 1,024-token cap can limit reasoning; no allowance was raised during this run.

To reconstruct one native row without generation, use the 2.23.0 candidate
source checkout until that version is published:

```bash
python3 - <<'PYCODE'
import json
from pathlib import Path

data = json.loads(Path("docs/data/model-comparison-2026-10-29.json").read_text())
row = next(row for row in data["rows"] if row["model"] == "gemini-4-argon")
config = json.loads(Path(data["method"]["case_source"]).read_text())
config.update(row["configuration"])
with Path("comparison.json").open("x") as output:
    output.write(json.dumps(config, indent=2) + "\n")
PYCODE
llm-preflight comparison.json --contract-check
llm-preflight comparison.json --doctor
llm-preflight comparison.json --pricing-check
llm-preflight comparison.json --dry-run
```

The snippet refuses to overwrite an existing config. Inspect current route,
price freshness, reasoning/output allowance and request limits before approving
a paid rerun. Local fixture checks do not execute application parser code.

## 2026-10-14 bounded comparison

The owner-approved run used **2.21.2**, eight unchanged synthetic support-routing
and JSON cases twice per model, concurrency one, no warmups, and one attempt per
request. All **192** planned calls were attempted; **163** returned API responses,
**160** passed their configured validator, and **three** responses failed it.
The other **29** calls were API errors. No retries, alternative routes or extra
paid probes were made.

| Provider route | Exact API model ID | Observed date | Valid / 16 | Mean latency | Estimated cost / 16 |
|---|---|---|---:|---:|---:|
| Anthropic | `claude-opus-5-5` | 2026-10-14 | 16 | 1.985s | $0.013220 |
| Anthropic | `claude-sonnet-5-5` | 2026-10-14 | 16 | 1.095s | $0.005740 |
| Anthropic | `claude-haiku-5-5` | 2026-10-14 | 16 | 0.934s | $0.000479 |
| OpenAI | `gpt-6.1-sol` | 2026-10-14 | 16 | 1.674s | $0.005112 |
| OpenAI | `gpt-6-luna` | 2026-10-14 | 16 | 2.150s | $0.000353 |
| Gemini | `gemini-4-argon` | 2026-10-14 | 16 | 2.376s | $0.005546 |
| Gemini | `gemini-3.8-flash` | 2026-10-14 | 16 | 2.255s | $0.005666 |
| OpenRouter / Relace | `z-ai/glm-5.3` | 2026-10-14 | 11 | 1.221s | — |
| OpenRouter / Relace | `z-ai/glm-5.3-flash` | 2026-10-14 | 16 | 1.535s | $0.000178 |
| OpenRouter / Relace | `deepseek/deepseek-v4.1-flash` | 2026-10-14 | 16 | 2.342s | $0.000745 |
| OpenRouter / Alibaba US | `qwen/qwen3.8-max-0902` | 2026-10-14 | 0 | — | — |
| OpenRouter / Alibaba US | `qwen/qwen3.8-flash` | 2026-10-14 | 5 | 1.077s | — |

The [machine-readable aggregates](../data/model-comparison-2026-10-14.json)
include exact request settings, price evidence, request and failure counts,
latency percentiles, token usage, CLI exits and hashes of the privately retained
configs/results. The known subtotal is **$0.0381288036** across **163** calls
with usage. **Total cost is unknown:** the other 29 calls returned no token
usage. Unknown amounts remain null; API errors are not assumed free. The
approved maximum token-based estimate was **$5.73**, not an invoice guarantee.

### Failures and interpretation

- **Qwen 3.8 Max-0902, OpenRouter / Alibaba US:** all 16 requests returned HTTP
  400 because the prepared request set `reasoning.enabled: false` while the
  endpoint requires reasoning. This configuration failed before model output;
  the row provides no quality or latency result for Qwen Max.
- **Qwen 3.8 Flash, OpenRouter / Alibaba US:** ten HTTP 429 responses identified
  the upstream shared provider pool as rate-limited. Of the six API successes,
  five passed. One invoice request selected `account`; the fixed contract
  required `billing`.
- **GLM 5.3, OpenRouter / Relace:** three HTTP 429 responses identified the
  upstream shared pool as rate-limited. Of 13 API successes, 11 passed. Both
  invoice-request repetitions selected `account` instead of `billing`.
- **The other nine models:** all 16 API calls and validators passed for each.
  This includes native Gemini 4 Argon and routed GLM 5.3 Flash. These are
  passing candidates for this example, not production approval.

All three retained invalid responses were reevaluated locally with the
unchanged validators and failed again. The configured retention policy saved
failure responses only: passing response text was discarded, so its verdicts
cannot be independently replayed from the retained text. Per-request verdicts,
usage, timings and method fingerprints remain available privately. The public
aggregate file contains no responses, account identifiers, credentials or
local paths.

### Request settings and reproducibility

- The eight cases match the [Anthropic comparison example](../../examples/anthropic-5.5-comparison.json).
  A SHA-256 of the case set pins the prompts and validators.
- Anthropic, OpenAI and Gemini used native routes. OpenRouter requests pinned
  Relace for GLM/DeepSeek and `alibaba/us-east-1` for Qwen, with fallback disabled.
  These are requested provider pins; no equivalent native Z.ai/DeepSeek/Qwen
  route was measured.
- Argon used `LOW` thinking with a **32,768**-token output/thinking cap; Gemini
  3.8 Flash used `LOW` with **512**. Routed GLM/DeepSeek used low reasoning;
  Qwen requested disabled reasoning, which Max rejected. Anthropic/OpenAI used
  provider-default reasoning. Temperature was omitted throughout.
- Every other output cap was 512. Mean latency includes only successful API
  responses, including outputs that failed the validator. It excludes API
  errors. Model blocks were sequential on one host; this small sample does not
  establish stable quality, latency or cost rankings. It does not exercise
  long context, complex agents, tools or multimodal inputs. Recorded usage
  includes 384 cached input tokens for GLM 5.3 and 192 for GLM 5.3 Flash;
  costs include their cached-input rates. However, cache-hit rates and savings
  were not systematically tested.

To reconstruct one row from the source checkout, combine the shared example
with its aggregate configuration. This creates a local plan without generation:

```bash
python3 - <<'PYCODE'
import json
from pathlib import Path

data = json.loads(Path("docs/data/model-comparison-2026-10-14.json").read_text())
row = next(row for row in data["rows"] if row["model"] == "gemini-4-argon")
config = json.loads(Path(data["method"]["case_source"]).read_text())
config.update(row["configuration"])
with Path("comparison.json").open("x") as output:
    output.write(json.dumps(config, indent=2) + "\n")
PYCODE
llm-preflight comparison.json --doctor
llm-preflight comparison.json --pricing-check
llm-preflight comparison.json --dry-run
```

The snippet refuses to overwrite an existing `comparison.json`. Review the
route, reasoning, current prices, output cap, retained response policy
and explicit request/cost limits before approving paid execution. Reconstructing
the Qwen Max row reproduces the rejected configuration; it is not a recommended
request. The [OpenRouter model page](https://openrouter.ai/qwen/qwen3.8-max-0902)
describes configurable reasoning effort; the recorded endpoint rejected
reasoning-disabled requests. Do not infer a current endpoint's parameter support
from a different model in the same family.

## Historical method (September 28–October 7)

- Eight support-routing and JSON cases were run twice per model, with no
  warmups, one attempt, concurrency one, and a 512-token output limit.
- The September runs did not set `temperature`. The October Anthropic
  configurations requested zero, which the native client omitted for both
  models. Those runs used the source checkout before the **2.19.1** release;
  that release includes the Haiku request compatibility and pricing update.
- Validation checked the configured exact labels or raw JSON contract. A
  provider request can succeed while the returned response fails that
  contract. The JSON cases did not use native schema output; a real app should
  use its own request settings and parser.
- Qwen3.8 Flash used `reasoning.enabled: false` through OpenRouter after a
  32-token default-reasoning probe produced no visible answer. The other five
  original OpenRouter routes used default reasoning. The new GLM-5.3 run
  used `low` reasoning and pinned Relace with fallback disabled. GPT-6.1 Sol
  used the Responses API with default reasoning. An exact model ID alone
  therefore does not reproduce every row's request.
- Cost is estimated from reported token usage and the reviewed price snapshot:
  direct-provider official rates or the dated OpenRouter route rates.
  It is the cost of these 16 calls, not a task price or invoice. Original
  OpenRouter runs did not record their selected hosting endpoint. The new
  GLM run was pinned to Relace, whose endpoint rates were checked immediately
  before execution.
- Runs occurred in sequential blocks from one host. Sixteen calls per model
  do not establish stable latency or quality rankings.

## Comparison results

These historical rows retain the latest observation from September 28 through
October 7. The October 14 run above is separate and does not erase failures.

| Provider | Exact API model ID | Observed date | Valid / 16 | Mean latency | Estimated cost / 16 |
|---|---|---|---:|---:|---:|
| Anthropic | `claude-haiku-5-5` | 2026-10-07 | 16 | 1.090s | $0.000481 |
| Anthropic | `claude-sonnet-5-5` | 2026-10-07 | 16 | 1.390s | $0.005740 |
| OpenAI | `gpt-6.1-sol` | 2026-09-30 | 16 | 2.071s | $0.004802 |
| OpenRouter / Relace | `z-ai/glm-5.3` | 2026-09-30 | 14 | 0.948s | $0.001190 |
| OpenAI | `gpt-5.6-sol` | 2026-09-28 | 16 | 1.480s | $0.008604 |
| OpenAI | `gpt-5.6-terra` | 2026-09-28 | 16 | 1.224s | $0.005084 |
| OpenAI | `gpt-5.6-luna` | 2026-09-28 | 16 | 1.209s | $0.000507 |
| OpenAI | `gpt-6-sol` | 2026-09-28 | 16 | 1.865s | $0.005392 |
| OpenAI | `gpt-6-luna` | 2026-09-28 | 16 | 1.361s | $0.000350 |
| OpenAI | `gpt-6-astra` | 2026-09-28 | 16 | 2.184s | $0.024610 |
| Anthropic | `claude-opus-4-8` | 2026-09-28 | 16 | 1.367s | $0.014815 |
| Anthropic | `claude-opus-5-5` | 2026-09-28 | 16 | 2.041s | $0.012120 |
| Anthropic | `claude-fable-5-1` | 2026-09-28 | 16 | 3.170s | $0.029250 |
| Anthropic | `claude-sonnet-5` | 2026-09-28 | 14 | 1.821s | $0.006396 |
| Anthropic | `claude-haiku-4-5-20251001` | 2026-09-28 | 6 | 0.940s | $0.002816 |
| Gemini | `gemini-3.5-flash` | 2026-09-28 | 15 | 2.406s | $0.047097 |
| Gemini | `gemini-3.8-flash` | 2026-09-28 | 16 | 2.363s | $0.014768 |
| Gemini | `gemini-3.1-flash-lite` | 2026-09-28 | 16 | 0.977s | $0.000588 |
| Gemini | `gemini-3.1-pro-preview` | 2026-09-28 | 16 | 4.140s | $0.064476 |
| xAI | `grok-4.7` | 2026-09-28 | 16 | 2.476s | $0.014304 |
| xAI | `grok-4.6` | 2026-09-28 | 16 | 5.496s | $0.010674 |
| OpenRouter | `qwen/qwen3.8-max-0902` | 2026-09-28 | 16 | 4.186s | $0.012932 |
| OpenRouter | `qwen/qwen3.8-flash` | 2026-09-28 | 16 | 1.459s | $0.000274 |
| OpenRouter | `deepseek/deepseek-v4-pro-0813` | 2026-09-28 | 16 | 3.768s | $0.004166 |
| OpenRouter | `deepseek/deepseek-v4.1-flash` | 2026-09-28 | 16 | 0.963s | $0.001863 |
| OpenRouter | `moonshotai/kimi-k3` | 2026-09-28 | 16 | 3.916s | $0.034866 |
| OpenRouter | `moonshotai/kimi-k2.6` | 2026-09-28 | 15 | 3.005s | $0.012846 |

## Anthropic 5.5 live checks

The owner-approved 2026-10-07 run completed **150 API requests**, with no
API failures or retries. Each model ran the original eight support-routing
and JSON cases twice, all ten built-in profiles, and a separate `agent-smoke`.
The original questions and validators were unchanged.

| Exact API model ID | Original questions / 16 | Full checks / 53 | Smoke / 6 | Estimated cost / 75 |
|---|---:|---:|---:|---:|
| `claude-haiku-5-5` | 16/16 | 53/53 | 5/6 | $0.0014602 |
| `claude-sonnet-5-5` | 16/16 | 53/53 | 6/6 | $0.0221540 |

The full run used two repetitions for ordinary cases and concurrency levels
1, 5 and 10, making 2, 5 and 10 requests at those levels respectively. Smoke
ran each of its six cases once per model. Every request used a 512-token
output limit and no warmups or retries. These short concurrency bursts are
not a sustained load test.

Haiku's password-reset smoke case returned `technical` where the existing
check required `account`; its separate full-profile calls passed that case
twice. The failed smoke remains a failed observation. Sonnet passed every
check. Overall, **149/150** outputs passed, at **$0.0236142** total estimated
cost. This total covers all three runs; the main table's latency and cost
cover only the 16 original questions per model.

The original-question usage was 1,560 input and 650 output tokens for Haiku,
and 1,560 input and 262 output tokens for Sonnet. All 150 calls had complete
reported usage and price coverage, with zero reported cache reads or writes.
These results therefore do not measure the Sonnet cache discount or Haiku's
long-context band; deterministic protocol tests cover that accounting.
Sonnet's previous 2026-09-28 result was 16/16, 1.258s mean latency and
$0.005740 estimated cost; the main table now shows its October observation.

The [Anthropic comparison example](../../examples/anthropic-5.5-comparison.json)
reproduces the 32 original-question requests with a $0.15 estimated-cost cap.
The [full-check example](../../examples/anthropic-5.5-checks.json) selects all
built-in profiles, with 106 requests and a $0.50 cap. Selecting `agent-smoke`
with `--smoke` reduces that plan to 12 requests. Use **2.19.1** or newer and
`ANTHROPIC_API_KEY` for these configurations:

```bash
python3 -m llm_preflight examples/anthropic-5.5-comparison.json --pricing-check
python3 -m llm_preflight examples/anthropic-5.5-comparison.json --dry-run
python3 -m llm_preflight examples/anthropic-5.5-checks.json --dry-run
python3 -m llm_preflight examples/anthropic-5.5-checks.json --tests agent-smoke --smoke --dry-run
```

The respective maximum planning estimates were $0.0883764, $0.2713263 and
$0.0245973, using the reviewed prices and token limits. Preview the plan and
review it before removing `--dry-run` for paid requests.
To reuse an env file outside `examples/`, add `--env-file PATH` to select it
explicitly; the default env-file location is beside each configuration.

All 150 saved responses were reevaluated locally and costs recomputed. The
full-profile wrapper ended with status 143 after saving and printing complete
results; its CLI exit code was not retained. The matching saved result and
stdout contained all 106 successful, valid responses, which were verified
without repeating paid calls. Raw artifacts, configuration hashes and this
execution-metadata gap remain in the maintainer's private evidence store.

## GPT-6.1 Sol measured run

The [GPT-6.1 comparison example](../../examples/gpt-6.1-sol-comparison.json)
contains the same eight synthetic cases, twice each, through the Responses
API. It declares 16 requests, no retries or warmups, a 512-token output limit,
and a $0.10 estimated-cost cap. With the reviewed standard rates, its maximum
estimate is $0.084730, including a possible cache-write premium.

```bash
python3 -m llm_preflight examples/gpt-6.1-sol-comparison.json --pricing-check
python3 -m llm_preflight examples/gpt-6.1-sol-comparison.json --dry-run
```

The approved run completed all 16 requests without retries or validation
failures. Reported usage was 1,096 input and 261 output tokens, with no
reported cache reads or writes; cost coverage was complete for all 16 calls.
The estimated total was $0.004802. See the
[pricing and request limits](current-snapshots.md#gpt-61-sol-pricing-and-request-limits).
The 2026-09-28 cost estimates predate cache-write accounting; they exclude any
write charges that were not retained in those runs' usage evidence.

## GLM-5.3 measured route and native example

The [routed comparison example](../../examples/glm-5.3-openrouter-comparison.json)
reproduces the observed OpenRouter / Relace run: eight cases twice, `low`
reasoning, 512 output tokens, no retries or warmups, and fallback disabled.
The 16 requests had a $0.10 estimated-cost cap and a maximum estimate of
$0.03290288. Relace rates reviewed for that run were $0.12 input, $0.12 cache
reads, and $4.00 output per million tokens, checked against the
[endpoint catalogue](https://openrouter.ai/api/v1/models/z-ai/glm-5.3/endpoints).
The example's route prices were re-reviewed on 2026-10-16 at $0.0608 input,
$0.0565 cache reads and $4.40 output per million tokens, which raises its
maximum estimate to $0.0361131392; past measurements used the prices of their
day. The current example was reviewed again on 2026-10-26: Relace's endpoint
catalogue lists $0.0703 input, $0.0703 cache reads and $4.3843 output per million
tokens, giving a maximum estimate of $0.0359952028. This configuration refresh
does not change the historical observations or their recorded costs.

All requests completed successfully; 14 outputs passed the configured
contract. Reported usage was 1,148 input tokens (448 cached) and 263 output
tokens. All 16 costs were known, including the two invalid outputs; the
estimated total was $0.00118976, rounded in the table. The CLI decision was
`fail` because two outputs failed validation. This run used `OPENROUTER_API_KEY`.
The native Z.ai route was not tested because `ZAI_API_KEY` was unavailable.

```bash
python3 -m llm_preflight examples/glm-5.3-openrouter-comparison.json --pricing-check
python3 -m llm_preflight examples/glm-5.3-openrouter-comparison.json --dry-run
```

The separate [native comparison example](../../examples/glm-5.3-comparison.json)
uses the same eight cases twice through Z.ai's standard Chat Completion API.
It selects `low` reasoning, 512 output tokens, no retries or warmups,
16 requests, and a $0.10 estimated-cost cap. The maximum estimate is
$0.0376184 at the reviewed native rates. Its figures are planning estimates;
the measured table row applies to OpenRouter / Relace.

```bash
python3 -m llm_preflight examples/glm-5.3-comparison.json --pricing-check
python3 -m llm_preflight examples/glm-5.3-comparison.json --dry-run
```

Use `ZAI_API_KEY` for the native example. Native API pricing and access
remain separate from the tested OpenRouter route.

## What the lower scores mean

- **GLM-5.3 through Relace** had two validation failures: one
  `ticket-extraction` call had no visible response and failed raw-JSON parsing;
  one `invoice-request` response selected `account` where this case required
  `billing`. The other 14 outputs passed. These observations describe the
  tested route and settings, not an untested native Z.ai endpoint.
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
