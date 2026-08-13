# LLM Preflight

![llm-preflight running the no-key demo: init, benchmark run, results table, quality gate, and decision block](https://raw.githubusercontent.com/feronovak/llm-preflight/main/docs/images/readme-demo.gif)

Know whether an AI-generated LLM integration is safe before it reaches
production. LLM Preflight is the local validation gate for model, prompt,
structured-output, and provider-call changes. It runs a small cross-provider
preflight and compares validated output, response speed, tokens, and estimated
cost.

It is a local preflight tool—not a hosted evaluation platform, tracing system,
RAG framework, or public leaderboard. Its results are evidence for your
account, network, prompts, and validation rules.

## Purpose

**Mission:** make every LLM integration change evidence-based before production.

**Vision:** AI-assisted software delivery where an agent can validate its LLM
changes as routinely as it runs tests, while people retain control of spend and
production approval.

**Positioning:** LLM Preflight is the fast, local, cross-provider validation
gate for AI-powered application changes. It is not a general evaluation,
observability, or autonomous-deployment platform.

It is built for engineers and coding agents working on AI features: teams that
need to check a real application contract against live model APIs before a
model ID, prompt, parser, tool definition, or provider option ships. Read the
[product positioning](https://github.com/feronovak/llm-preflight/blob/main/docs/product/positioning.md)
and the [AI implementation testing guide](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/agent-validation.md)
for the intended workflow and boundaries.

> [!WARNING]
> Live benchmarks make paid API requests. Start with the no-key demo, preview
> the plan before a live run, and keep limits and repetitions small.

## Try it in 60 seconds

Create and run a deterministic local benchmark—no API key or network request:

```bash
llm-preflight init
llm-preflight benchmark.json --no-save
```

From a source checkout:

```bash
python3 -m llm_preflight init
python3 -m llm_preflight benchmark.json --no-save
```

`init` never overwrites an existing config. It creates a mock benchmark so
you can see the report and exit behavior before making a paid request.
Its result is intentionally `inconclusive` (exit code `3`): a local mock
validates configuration and output handling, but cannot approve a live model.

## What is new in 2.5–2.6

- **Match the deployed JSON consumer.** Use `json_set`, `first_fenced_block`,
  or `first_json_value` only when those are the parsing rules your application
  actually uses.
- **Require current pricing before paid work.** `--pricing-check` reports
  every selected billable route as priced, undated, stale, or unknown, with a
  source and remediation. Set `require_current_pricing` to block paid runs
  until that coverage is current.

## Next release

The in-development 2.7.0 source adds a schema-versioned agent decision object:
`pass`, `fail`, or `inconclusive`, with exact blocking warnings and a safe next
command. It appears in saved JSON and MCP results so automation need not parse
terminal output. See the [agent decision contract](https://github.com/feronovak/llm-preflight/blob/main/docs/reference/decision.md).
Mock-only runs intentionally produce `inconclusive`, while API and contract
failures have separate remediation commands.

## Use it when

- You are switching models or providers.
- A provider publishes a new model or changes a `latest` alias.
- You need to compare your own prompt's validity, latency, and cost.
- You want local result artifacts instead of a hosted dashboard.

It measures deterministic test validity, end-to-end latency (p50/p95), time to
first token, throughput when the stream is incremental and usage is available,
token totals, and estimated cost. Result files retain request metadata and per-request observations for
reproducibility.

"Deterministic" describes the validator, not the model: every response is
checked against explicit structural rules — a regular expression, a JSON shape,
an exact routing label — so the same response always produces the same verdict.
The tool does not score semantic quality; that is your task-specific
evaluation, and it stays out of scope on purpose.

## What a live run reports

Real output from a cross-provider run (2026-07-16, one short support prompt,
three repetitions per model, total spend under $0.05):

| Model | Success | Latency p50 | Latency p95 | TTFT p50 | Tokens/s p50 | Cost |
|---|---:|---:|---:|---:|---:|---:|
| gpt-5.6-luna | 100% | 1.379s | 1.579s | 0.726s | 139.0 | $0.001686 |
| gpt-5.4-mini | 100% | 1.779s | 3.628s | 1.061s | 126.6 | $0.001143 |
| claude-fable-5 | 100% | 6.497s | 7.573s | 2.908s | 56.5 | $0.033610 |
| claude-opus-4-8 | 100% | 3.859s | 4.267s | 1.350s | 54.3 | $0.010205 |
| gemini-3.5-flash | 100% | 2.924s | 2.955s | 2.895s | n/a | $0.001084 |
| minimax-m3 | 100% | 3.356s | 3.631s | 1.719s | 90.4 | n/a |

Tokens/s reads `n/a` when a provider delivers the response as a terminal
burst instead of an incremental stream — the observable window measures
transport, not generation, so no rate is reported. Cost reads `n/a` when
pricing for the model is unknown.

The report ends with a decision block:

```
- Fastest: gpt-5.6-luna — 1.423s mean latency.
- Cheapest: gemini-3.5-flash — $0.001084 total.
- Best value: gpt-5.6-luna — 88% composite score.
- Recommended: gpt-5.6-luna — passed every selected test and led the
  qualified value ranking.
```

Numbers like these are evidence for one environment at one time, not a
leaderboard. Latency depends on your network and region; run the preflight
from the host that will serve production traffic.

The same comparison can be driven interactively — pick models and tests at
the terminal, read the cost ceiling before anything is sent, watch each
request report its own cost, and end on the decision. This capture is a real
two-model paid run that cost half a cent
([config](https://github.com/feronovak/llm-preflight/blob/main/examples/flagship-comparison.json),
[details](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/interactive-runs.md)):

![Interactive comparison of two commercial models on two custom chat prompts, from selection through cost preview to the results table and decision](https://raw.githubusercontent.com/feronovak/llm-preflight/main/docs/images/interactive-demo.gif)

## First live run

Python 3.10+ is required. There are no third-party runtime dependencies:
`pip install llm-preflight` installs this package and nothing else, and the
CLI runs on the Python standard library alone. Development tools (pytest,
ruff, mypy) are optional extras that never reach a production install.

```bash
cp benchmark.example.json benchmark.json
cp .env.example .env.production
# Edit benchmark.json and add only the provider keys you use.
python3 -m llm_preflight benchmark.json --dry-run
python3 -m llm_preflight benchmark.json
```

The CLI reads `.env.production` beside the config without overriding environment
variables already set by your shell. Use `--no-env-file` or `--env-file PATH`
when needed. Runs print a terminal report and, unless `--no-save` is used,
write JSON and Markdown results under `results/`.

Install the command globally in a virtual environment if preferred:

```bash
python3 -m pip install llm-preflight
llm-preflight --init
```

Run `--doctor` and `--dry-run` before the final command. They make no generation
requests; the final command is the paid work.

## Change a model safely

This is the core workflow. Put your approved model and candidate model in one
config, then run the small response-and-contract preflight:

```bash
llm-preflight benchmark.json --migration-check --dry-run
llm-preflight benchmark.json --migration-check
```

It sends three short representative cases to each selected model, once each.
It answers: did the API work, did each response meet the basic contract, and
how quickly did the provider start and finish responding? It is a cheap
compatibility check, not a statistical performance conclusion.

When that passes, run the task-specific checks that match your application—for
example `exact-routing-check` or `structured-output-check`—before approving a
switch.
Use [custom contract tests](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/output-contracts.md) to express the outputs your
own feature must preserve.

## Using a coding agent

Give an agent the same evidence you would use yourself: a reviewed config, an
explicit output contract, and a dry run before paid work. Start with the
recommended five-check suite:

```bash
# No generation request: inspect credentials, model selection, and paid-work plan.
llm-preflight benchmark.json --doctor --json
llm-preflight benchmark.json --tests agent-smoke --smoke --dry-run --json

# Paid run, only after reviewing the plan.
llm-preflight benchmark.json --tests agent-smoke --smoke --json --no-save
```

An agent should not infer model IDs, weaken a validator to turn a failure into
a pass, or approve a model without an explicit instruction. The compact
[LLM and coding-agent guide](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/coding-agents.md)
covers commands, result JSON, exit codes, and automation guardrails. The
[AI implementation testing guide](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/agent-validation.md)
shows how to make this validation an agent's default testing step.

## MCP for coding agents

Use the local stdio MCP server when an agent needs the preflight evidence
without shell parsing or arbitrary command execution:

```json
{
  "mcpServers": {
    "llm-preflight": {
      "command": "llm-preflight-mcp",
      "args": ["--workspace", "/absolute/path/to/repository"]
    }
  }
}
```

It exposes only four tools: validate a config, prepare a dry-run plan, run an
explicitly confirmed preflight, and compare saved baselines. The first, second,
and fourth tools never contact providers or load credentials. A live run still
needs an explicit paid-run confirmation. See the [MCP server guide](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/mcp.md) for tool
semantics, workspace boundaries, and the safe agent workflow.

## Choose your path

**I am new and want to see the tool safely.** Start with the
[Getting started guide](https://github.com/feronovak/llm-preflight/blob/main/docs/getting-started/safe-demo.md). It uses a no-key local mock
before any provider request.

**I know the current and candidate model IDs.** Edit one config, run the
[migration check](#change-a-model-safely), then add a
[custom contract test](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/output-contracts.md) for the output your feature must
preserve. You do not need the catalogue.

**I want to find and review provider releases.** Use the local catalogue
lifecycle below. It keeps broad provider metadata separate from the small set
of models you approve for ongoing testing.

```bash
llm-preflight catalog init
llm-preflight catalog refresh benchmarks/watch.json
# If a model is shown as “Needs one probe”, review and confirm a minimal request:
llm-preflight catalog probe benchmarks/watch.json
llm-preflight catalog prepare benchmarks/watch.json \
  --against benchmarks/approved.json --output benchmarks/candidates.json
llm-preflight benchmarks/candidates.json --interactive \
  --approve-to benchmarks/approved.json
```

Refresh reads metadata only. A probe sends one minimal request only for text
candidates you select and confirm. The interactive benchmark then lets you
approve passing models explicitly. Follow the complete
[catalogue tutorial](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/model-catalog.md) for the decision points.

**I am automating an established contract.** Use
[CI and JSON output](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/ci.md), with a saved baseline and `--ci` where a
regression should fail the pipeline.

## Useful commands once you know your path

```bash
# Inspect configuration, credentials, and model selection without generation.
llm-preflight benchmark.json --doctor
llm-preflight benchmark.json --dry-run
llm-preflight benchmark.json --pricing-check

# Run a reduced live benchmark.
llm-preflight benchmark.json --smoke

# Run a single ad hoc prompt.
llm-preflight --quick "Return only valid JSON with a status field." \
  --models openai:gpt-5.4-mini
```

For advanced discovery, interactive runs, CI, baselines, replay, and stop
modes, see [workflows](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/model-change.md). For models, environment files,
custom prompts, and provider-specific options, see
[configuration](https://github.com/feronovak/llm-preflight/blob/main/docs/reference/configuration.md).

## What makes a comparison useful

- Keep prompts, system instructions, temperature, and output limits fixed.
- Validate outputs: a fast malformed response is a failed result.
- Run from the same host; network distance and provider load affect latency.
- Treat single-user latency and load testing as separate experiments.
- Prefer dated model IDs over moving aliases.

The CLI distinguishes `API FAIL` (transport, credentials, provider, or request
failure) from `API OK / TEST FAIL` (a response that fails your validator).
Recommendations only consider models that pass every selected test.

## How it compares

Several good tools live near this space. Use them when their job is your job:

- **promptfoo, deepeval** — full evaluation suites: scored quality metrics,
  red-teaming, large ongoing test matrices in CI. Use them to grade prompt and
  model quality over time.
- **llmci** — CI merge gates and prompt migration; it rewrites prompts for a
  new model. Use it when the prompt should adapt to the model.
- **Braintrust, LangSmith** — hosted platforms: tracing, dashboards, team
  collaboration, production observability.
- **`llm` (Simon Willison)** — a general multi-provider CLI for running
  prompts, not a comparison harness.

LLM Preflight does one narrower job: the local go/no-go check in the moment
before a model switch. Your prompt, candidate models, structural validation,
latency, and cost — one command, one report, no hosted service, no telemetry,
and no vendor between you and the verdict.

## Documentation

Start at the [documentation homepage](https://github.com/feronovak/llm-preflight/blob/main/docs/index.md), then choose the path that matches your work:

- **Start safely:** [safe demo](https://github.com/feronovak/llm-preflight/blob/main/docs/getting-started/safe-demo.md) and
  [model change](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/model-change.md).
- **Validate a change:** [output contracts](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/output-contracts.md),
  [model catalogue](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/model-catalog.md), and
  [pricing and safety](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/pricing-and-safety.md).
- **Automate:** [CI and JSON output](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/ci.md),
  [coding agents](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/coding-agents.md), and
  [MCP](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/mcp.md).
- **Look up details:** [CLI reference](https://github.com/feronovak/llm-preflight/blob/main/docs/reference/cli.md),
  [configuration](https://github.com/feronovak/llm-preflight/blob/main/docs/reference/configuration.md),
  [result JSON](https://github.com/feronovak/llm-preflight/blob/main/docs/reference/results.md), and
  [troubleshooting](https://github.com/feronovak/llm-preflight/blob/main/docs/operations/troubleshooting.md).
- **Understand the product:** [positioning](https://github.com/feronovak/llm-preflight/blob/main/docs/product/positioning.md) and
  [AI implementation testing](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/agent-validation.md).
- [Contributing](https://github.com/feronovak/llm-preflight/blob/main/CONTRIBUTING.md) — development setup and the TDD workflow.
- [Security](https://github.com/feronovak/llm-preflight/blob/main/SECURITY.md) — reporting vulnerabilities.

## Contributing and license

Contributions are welcome; see [CONTRIBUTING.md](https://github.com/feronovak/llm-preflight/blob/main/CONTRIBUTING.md). Released
under the [MIT License](https://github.com/feronovak/llm-preflight/blob/main/LICENSE).
