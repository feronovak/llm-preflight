# LLM Preflight

<!-- mcp-name: io.github.feronovak/llm-preflight -->

**Last reviewed:** 2026-10-19 · **As of:** v2.22.2

[![PyPI](https://img.shields.io/pypi/v/llm-preflight)](https://pypi.org/project/llm-preflight/)
[![Tests](https://github.com/feronovak/llm-preflight/actions/workflows/tests.yml/badge.svg)](https://github.com/feronovak/llm-preflight/actions/workflows/tests.yml)
[![License](https://img.shields.io/github/license/feronovak/llm-preflight)](https://github.com/feronovak/llm-preflight/blob/main/LICENSE)

**Check LLM responses against the output rules your application depends on—before changing a model, prompt, schema, or provider.**

Define the JSON shape, routing labels, or exact output your feature needs.
Check responses against those rules, preview provider requests and estimated
cost, and keep evidence for the change review.

Built for engineers maintaining an LLM feature. Runs locally as a CLI, GitHub
Action, or MCP server. Python 3.10+; no third-party runtime dependencies.

[Try it](#try-it-in-60-seconds) · [Observed models](#observed-results-on-a-support-routing-contract) · [Use your own contract](#first-live-run) · [CI and agents](#cli-ci-and-mcp)

**Watch an invalid response get caught and fixed (23 seconds).**

`billing` passes → change the response to `sales` → check fails → restore
`billing` → check passes. The allowed labels stay unchanged.

![Real terminal session: billing passes, sales fails the same validator, and restoring billing passes again](https://raw.githubusercontent.com/feronovak/llm-preflight/main/docs/images/contract-check-session.gif)

*Real CLI output with synthetic response fixtures. This checks the validator;
it makes no provider requests and does not execute your application's parser.*
[Watch the MP4](https://github.com/feronovak/llm-preflight/blob/main/docs/images/contract-check-session.mp4).

## Try it in 60 seconds

In a new directory, install the tool and run the local mock—no API key or
provider request:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install llm-preflight
llm-preflight init
llm-preflight benchmark.json --no-save --no-env-file
```

The activation command above is for POSIX shells; PowerShell uses
`.\.venv\Scripts\Activate.ps1`.

`init` refuses to overwrite an existing config. Look for `local-mock` with
`PASS` in the quality gate: the mock replied `ok` and passed the exact-output
test. The overall decision is `inconclusive` (exit `3`) because a local mock
provides no live-provider evidence. The demo worked; it cannot approve a model.
`--no-save` skips JSON/Markdown result artifacts; `--no-env-file` skips credential files.

### Watch the interactive default template (30 seconds)

Select the mock and default `Reply with ok` test, review the plan, and confirm
the local run. The session also reads the same decision through CLI JSON:

![Interactive default-template demo: select the mock and configured test, review the plan, run locally, and inspect the expected inconclusive result as JSON](https://raw.githubusercontent.com/feronovak/llm-preflight/main/docs/images/default-template-evidence-session.gif)

*Local test: passed. Live provider: not tested. No API keys or provider calls.*
[Watch the MP4](https://github.com/feronovak/llm-preflight/blob/main/docs/images/default-template-evidence-session.mp4)
or start with the [text walkthrough](https://github.com/feronovak/llm-preflight/blob/main/docs/getting-started/safe-demo.md)
and [interactive CLI JSON example](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/interactive-runs.md#default-template-walkthrough).

For benchmark runs, read the decision before acting:

- **`pass`, exit `0`:** the configured checks passed with the required evidence.
- **`fail`, exit `1`:** a configured check failed; inspect the cause.
- **`inconclusive`, exit `3`:** evidence is insufficient; read the blocking warnings.

A passing run is evidence for the configured workload, not production approval.

<a id="tested-models"></a>

## Observed results on a support-routing contract

These are selected real provider observations, including failed checks and
rejected requests. Each model received 16 requests. Dates, routes and request
settings differ; the results describe one workload and are not a general ranking.

[![Measured results for 14 models, including GPT, Claude, Gemini, GLM, DeepSeek and Qwen: checks passed, mean latency, estimated cost, date and actual route; partial failures, rejected requests and unknown costs remain visible](https://raw.githubusercontent.com/feronovak/llm-preflight/main/docs/images/measured-models.svg)](https://github.com/feronovak/llm-preflight/blob/main/docs/images/measured-models.svg)

Latency covers successful API responses, including contract failures, and
excludes API errors. `—` means unavailable; missing usage keeps total cost
unknown. OpenRouter observations do not establish native-provider behavior.
[Read the results as text, request settings, and failure analysis](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/observed-model-comparison.md).

<a id="purpose"></a>

## First live run

Start with one rule your application already enforces. The
[project integration guide](https://github.com/feronovak/llm-preflight/blob/main/docs/getting-started/project-integration.md)
provides a complete routing contract with accepted/rejected fixtures and a
no-spend pull-request check. Match your deployed prompt and response parser;
local fixture checks do not execute application code automatically.

To try a minimal provider starter instead:

```bash
llm-preflight init live.json --template provider \
  --provider openai --model gpt-6.1-sol --api-key-env OPENAI_API_KEY
```

The starter asks for exactly `ok`. Add this top-level field to `live.json`,
keeping its existing fields, to check the validator locally:

```json
{
  "validation_fixtures": [
    {"name": "accepted-label", "response": "ok", "expect": "pass"},
    {"name": "rejected-label", "response": "not ok", "expect": "fail"}
  ]
}
```

Set `OPENAI_API_KEY` in your shell or in an uncommitted `.env.production`
beside `live.json`. The config stores the variable name, never the key.
Preview the check without making a generation request:

```bash
llm-preflight live.json --contract-check
llm-preflight live.json --doctor
llm-preflight live.json --pricing-check
llm-preflight live.json --dry-run
```

The starter has a three-request limit and a $0.05 estimated-cost cap. Resolve
warnings and review the route, retry-expanded request bound, pricing and
retention settings. The starter saves failed responses by default; review
artifacts before sharing them.

**Paid request:** only after reviewing and authorizing that plan, run:

```bash
llm-preflight live.json
```

A direct CLI run has no separate approval prompt. Results are saved as JSON
and Markdown under `results/` unless you use `--no-save`. The CLI reads the
config-adjacent `.env.production` without replacing existing shell values;
choose another file with `--env-file PATH` or skip it with `--no-env-file`.

## Choose your path

- **Set up a real project.** Adapt one application rule with the
  [project integration guide](https://github.com/feronovak/llm-preflight/blob/main/docs/getting-started/project-integration.md).
- **Validate a change.** Compare approved and candidate configurations with the
  [model-change guide](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/model-change.md).
- **Automate an established contract.** Use
  [CI and JSON output](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/ci.md)
  or the [GitHub Action](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/github-action.md).
- **Configure a coding agent.** Start with
  `llm-preflight-mcp --workspace "$PWD"` in a trusted repository and follow the
  [MCP server guide](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/mcp.md).

<a id="what-live-evidence-looks-like"></a>

## See a contract change fail

A review artifact retains the decision, contract validity, latency, usage,
estimated cost and blocking warnings. Render saved schema-version-1 JSON as
a standalone report without another provider request. Substitute the saved
JSON path printed by your run for `results/run.json`:

```bash
llm-preflight report results/run.json --output report.html
```

The renderer omits prompts, responses, local paths and identifying run metadata.
For reproducible examples, run these from a **source checkout**:

```bash
python3 -m llm_preflight report examples/reports/schema-baseline.json --format markdown
python3 -m llm_preflight report examples/reports/schema-break.json --format markdown
```

The first synthetic result passes; the second reports `contract_failure`, 67%
contract validity and one contract-only failure. The
[report gallery](https://github.com/feronovak/llm-preflight/tree/main/examples/reports)
also demonstrates a gate blocked with `no_record` (exit `1`). These fixtures
make no provider calls and cannot supply attested CI evidence.

## CLI, CI, and MCP

Works as a CLI, GitHub Action, and local MCP server. The
[Action](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/github-action.md)
defaults to no generation requests; a live MCP run requires explicit paid-run
confirmation. Keep the client's tool approval enabled: its confirmation field
is not proof that a person authorized spending.

**No preflight, no merge.** With a required check configured, the offline gate
requires a fresh passing CI record matching the current contract, routes,
prompts and run selection. Protect the producer and gate workflows; signed
records also need `gh attestation verify` before the gate. Follow
[proof of preflight](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/proof-of-preflight.md)
to configure it. A local fixture pass or installed package does not enforce a
merge policy.

It doesn't certify production behaviour. It proves the check was done.

## MCP for coding agents

Configure the installed stdio command in your MCP client:

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

The seven tools audit literal model IDs, validate a config, preview a plan, run
a preflight, compare saved baselines, verify a record and gate CI evidence.
For an existing contract, begin with `validate_config` and `dry_run_plan`.
Agents must read the structured decision and report missing evidence.
See the [MCP guide](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/mcp.md)
for request/result examples and workspace boundaries.

<a id="using-a-coding-agent"></a>

The `agent-smoke` suite with `--smoke` makes six requests per model before
configured retries. Use the
[coding-agent workflow](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/coding-agents.md)
for CLI commands. An agent must not weaken a validator to get a pass or infer
permission for paid work from a gate result.

<a id="useful-commands-once-you-know-your-path"></a>

## Common jobs

- **Audit existing model IDs:** `llm-preflight --audit-source .` reports literal
  IDs marked retired or retiring in the bundled snapshot. No config or key is
  needed. Add `--ci` to make the retirement decision affect the exit code;
  without it, findings normally exit `0`. In Git, the scan reads tracked,
  unignored files. See [model retirements](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/retirements.md).
- **Inspect pricing:** `--doctor` provides pricing advisory;
  `--pricing-check` is the fail-closed coverage gate. Preview the run with
  `llm-preflight benchmark.json --dry-run`.
- **Review Git changes:** `llm-preflight benchmark.json --change-plan` proposes
  checks from static signals; it does not authorize execution.
- **Discover a candidate:** refresh metadata, prepare a plan and preview it:

  ```bash
  llm-preflight catalog refresh benchmarks/watch.json
  llm-preflight catalog prepare benchmarks/watch.json \
    --against benchmarks/approved.json --output benchmarks/candidates.json
  llm-preflight benchmarks/candidates.json --migration-check --dry-run
  ```

  Create the watch/approved files first with the
  [model catalogue guide](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/model-catalog.md).
  Catalogue probes are a separate, potentially billable step.

## Change a model safely

Put approved and candidate models in a reviewed config, then preview the
built-in compatibility pack:

```bash
llm-preflight benchmark.json --migration-check --dry-run
```

After approving that plan, `llm-preflight benchmark.json --migration-check`
sends three built-in cases per model before configured retries: a capital-city
answer, summary and rewrite. They check basic compatibility; use your own
[application contract tests](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/output-contracts.md)
to establish whether the change meets your feature's rules.

## Safety boundary

Results apply to the configured account, route, prompts and validators at one
time. Model responses remain stochastic. Deterministic validation checks the
rules you declare; it does not establish semantic accuracy or production safety.
Preview limits before live requests and keep paid-run authority with the person
responsible for the integration.

## How it compares

Use this project for a bounded contract check and reviewable evidence before
an integration change. Evaluation frameworks also support assertions and CI;
keep one when it already meets your needs. Broader evaluation suites serve
semantic scoring and statistical comparisons; observability tools serve
production tracing and incident investigation. See
[when to use it](https://github.com/feronovak/llm-preflight/blob/main/docs/product/when-to-use.md).

## Get help or try it in your project

[Ask for setup help or a contract example](https://github.com/feronovak/llm-preflight/issues/new?template=setup-help.yml).
Include the version, intended check and redacted output. Never share keys,
private prompts or provider responses. Use the
[security policy](https://github.com/feronovak/llm-preflight/blob/main/SECURITY.md)
for vulnerabilities.

## Documentation

The [documentation homepage](https://github.com/feronovak/llm-preflight/blob/main/docs/index.md)
routes by task. Consult [CLI reference](https://github.com/feronovak/llm-preflight/blob/main/docs/reference/cli.md),
[configuration](https://github.com/feronovak/llm-preflight/blob/main/docs/reference/configuration.md)
and [result JSON](https://github.com/feronovak/llm-preflight/blob/main/docs/reference/results.md)
for exact behavior. Native routes and dated pricing coverage are listed in
[current snapshots](https://github.com/feronovak/llm-preflight/blob/main/docs/guides/current-snapshots.md).
The [north star](https://github.com/feronovak/llm-preflight/blob/main/docs/NORTH_STAR.md)
and [AI implementation testing guide](https://github.com/feronovak/llm-preflight/blob/main/docs/automation/agent-validation.md)
explain the intended workflow and scope.

Release notes for every version are in the [changelog](https://github.com/feronovak/llm-preflight/blob/main/CHANGELOG.md).

## Contributing and license

See [Contributing](https://github.com/feronovak/llm-preflight/blob/main/CONTRIBUTING.md)
for development and documentation standards. Released under the
[MIT License](https://github.com/feronovak/llm-preflight/blob/main/LICENSE).
