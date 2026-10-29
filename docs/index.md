# LLM Preflight documentation

**Last reviewed:** 2026-10-19 · **As of:** v2.22.1

Check a declared application output rule before changing an LLM integration.
Choose a task below; each path explains the inputs, expected result and next step.

## Start here

- **Try it without an API key.** [Run the local demo](getting-started/safe-demo.md)
  and understand why a passing mock test still produces `inconclusive`.
- **Check my application.** [Set up one real contract](getting-started/project-integration.md)
  with accepted/rejected examples, existing credentials and request bounds.
- **Review a change.** [Compare approved and candidate configurations](guides/model-change.md)
  while preserving the application rule and reviewing the paid-work plan.
- **Automate an established check.** Use [CI and JSON output](automation/ci.md)
  for pipelines or [MCP](automation/mcp.md) for a coding agent.

<a id="start-safely"></a>

## Understand the result

- [Interactive walkthrough](guides/interactive-runs.md) — native menu choices,
  a local test, and a CLI JSON request/result example.
- [Reviewable reports](guides/reports.md) — export saved evidence without
  another provider request; understand what a report omits.
- [Synthetic report gallery](../examples/reports/README.md) — reproduce a
  passing result, a contract failure and a blocked gate from a source checkout.
- [Decision contract](reference/decision.md) — interpret pass, fail,
  inconclusive and blocking warnings in automation.
- [Troubleshooting](operations/troubleshooting.md) — diagnose a failed request,
  incomplete evidence or unexpected verdict.

<a id="tested-models"></a>

## Observed provider results

Read the [support-routing comparison](guides/observed-model-comparison.md) for
the **2026-10-29 measurement of 19 native models**: 152 requests, 144 validated
outputs, three contract failures and five rate-limit errors. The two
[README result panels](../README.md#observed-results-on-a-support-routing-contract)
show all 19 models. The guide includes the full table, settings, unknown-cost
evidence and earlier measurements as history.

These observations do not establish how a model performs on your application.
For supported routes and dated price coverage, use
[official snapshots](guides/current-snapshots.md); for native endpoint setup,
see [direct GLM, DeepSeek and Qwen checks](guides/native-chinese-models.md).

## Run and maintain preflights

- [Output contracts](guides/output-contracts.md) — declare JSON shapes, exact
  labels and other supported rules; prove accepted/rejected examples locally.
- [Model catalogue](guides/model-catalog.md) — discover metadata, deliberately
  probe candidates and prepare bounded plans.
- [Model retirements](guides/retirements.md) — audit literal IDs and understand
  snapshot freshness, replacements and exit behavior.
- [Pricing and safety](guides/pricing-and-safety.md) — review retries, estimated
  cost, unknown usage and response retention before provider work.
- [Image-to-text inputs](guides/vision-inputs.md) — check local inputs and
  response contracts; image generation is outside this workflow.

## Automate with confidence

- [GitHub Action](automation/github-action.md) — no-generation checks by
  default, with an explicit opt-in for provider requests.
- [GitHub Actions starter](automation/ci.md#github-actions-starter) — a fork-safe
  mock workflow that retains JSON and expects the mock's inconclusive exit.
- [Proof of preflight](guides/proof-of-preflight.md) — configure a required
  gate for fresh matching CI evidence, workflow protection and signature checks.
- [Coding-agent workflow](automation/coding-agents.md) — preserve validators,
  inspect bounded plans and keep paid-run authority with the user.
- [Git-aware change plans](automation/change-plans.md) — inspect static change
  signals and proposed checks without authorizing execution.

## Reference and help

- [CLI reference](reference/cli.md)
- [Configuration](reference/configuration.md) and [configuration reference](reference/configuration-schema.md)
- [Result JSON](reference/results.md) and [decision contract](reference/decision.md)
- [When to use this tool](product/when-to-use.md) and [product decisions](DECISIONS.md)
- [Product map](FEATURE_MAP.md) and [code map](PROJECT_MAP.md)
- [Changelog](../CHANGELOG.md), [contributing](../CONTRIBUTING.md) and [documentation writing guide](development/documentation.md)
- [Security reporting](../SECURITY.md)

[Ask for setup help or a contract example](https://github.com/feronovak/llm-preflight/issues/new?template=setup-help.yml)
with the version, intended check and redacted output. Keep credentials, private
prompts and provider responses out of public issues.
