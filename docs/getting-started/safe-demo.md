# Getting started

**Last reviewed:** 2026-10-19 · **As of:** v2.22.1

Run a local mock check, interpret its result, then choose a path for your own
application. This walkthrough requires Python 3.10+ and a terminal. It uses no
API key or provider request; installation needs access to the package index.

## First, see a safe local run

Use a new directory so an existing benchmark cannot be mistaken for the demo:

```bash
python3 -m pip install llm-preflight
llm-preflight init
llm-preflight benchmark.json --no-save --no-env-file
```

`init` creates one mock model and the prompt `Reply with ok.`, validated as
exactly `ok`. It refuses to overwrite an existing file. `--no-env-file` skips
credential files; `--no-save` skips JSON/Markdown result artifacts.

## Read the result

In the quality gate, `local-mock` shows `PASS`: its response met the exact-output
rule. The decision then explains why the run cannot approve a live model:

```text
Decision: inconclusive (exit 3)
Blocking warnings:
- Mock-only runs do not provide live-provider evidence.
```

**This is the expected result.** The local test passed; no provider was tested.
The executive recommendation is a summary of selected test results, not
permission to spend money or approve production.

For a benchmark, `pass` exits `0`, `fail` exits `1`, and `inconclusive` exits `3`.
A provider can return a usable API response that fails your output rule. A
missing cost is unknown, not zero. Automation should read JSON or the saved
JSON artifact rather than parse terminal output.

### Read the same decision as JSON

This remains a local mock run. The following shell sequence captures stdout
and checks that the expected inconclusive status was returned:

```bash
set +e
llm-preflight benchmark.json --json --no-save --no-env-file > mock-result.json
status=$?
set -e
test "$status" -eq 3
```

The result contains these fields (an excerpt):

```json
{
  "decision": {
    "state": "inconclusive",
    "blocking_warnings": [
      "Mock-only runs do not provide live-provider evidence."
    ]
  }
}
```

`mock-result.json` exists because the shell redirected stdout; `--no-save`
prevents the tool's normal saved-result artifacts. See the
[interactive walkthrough](../guides/interactive-runs.md#default-template-walkthrough)
for the same template with menus and a terminal recording.

### If your result differs

- **Config already exists:** use a fresh directory or choose a new filename.
  Keep an existing project config intact.
- **A key or provider is mentioned:** inspect `benchmark.json`; this walkthrough
  expects only `provider: mock`. An existing live config is a different task.
- **A script stops on exit 3:** capture the status explicitly as above. Accept
  `3` only when testing a known mock fixture; never treat unknown live evidence
  as a successful production gate.

## Reuse a project env file safely

For a real application, use the
[project integration guide](project-integration.md) to adapt one request and a
rule its consumer enforces. It provides accepted/rejected response fixtures and
a no-generation CI check. Local fixtures check the validator; keep your
application's parser tests separately.

For a minimal provider starter, use a different config path from the mock:

```bash
llm-preflight init live.json --template provider --interactive
llm-preflight live.json --doctor --json
llm-preflight live.json --pricing-check
llm-preflight live.json --dry-run --json
```

The setup asks for the provider, model, credential variable name and optional
existing env-file reference, never a secret value. The live starter limits
requests and estimated cost and saves failed responses by default. Keep the
actual key in your shell or an uncommitted env file; review saved artifacts
before sharing them.

A config-relative env file must stay within the config directory. Shell values
win over file values, `--env-file` overrides the configured reference, and
`--no-env-file` disables file loading. The commands above make no generation
requests. A direct `llm-preflight live.json` command can make paid requests
without a separate approval prompt; run it only after reviewing and authorizing
the plan.

## Then run a quick migration check

When comparing an approved model with a candidate, the optional
`--migration-check` pack runs three built-in cases: a capital-city answer,
summary and rewrite. Preview that exact selection with
`llm-preflight live.json --migration-check --dry-run`, resolving any request or
cost-limit errors before execution. These generic cases do not establish your
application's contract. Follow the [model-change guide](../guides/model-change.md)
for the complete review sequence.

## Choose your next path

- **Check an application:** adapt a [custom contract test](../guides/output-contracts.md)
  with the [project integration guide](project-integration.md).
- **Compare a change:** use [model-change workflows](../guides/model-change.md).
- **Find candidates:** follow the [model catalogue](../guides/model-catalog.md).
- **Automate:** use [CI and JSON output](../automation/ci.md) or
  [MCP for coding agents](../automation/mcp.md).
