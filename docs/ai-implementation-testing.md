# AI implementation testing

Use LLM Preflight as a coding agent's validation step whenever a change may
alter an application's LLM behavior. The goal is not to let an agent approve
its own deployment; it is to give the agent and reviewer reproducible evidence
before an LLM-related change is declared complete.

## When an agent should run it

Run the no-spend checks after changes to:

- a model ID, provider, endpoint, or request option;
- a prompt, system prompt, schema, validator, or response parser;
- a tool definition or structured output expected by the application; or
- an LLM benchmark configuration or its environment overlay.

Run the paid smoke check only after the repository's owner has authorized the
reviewed request count and cost.

## Default workflow

Start from a reviewed benchmark configuration that represents the deployed
prompt and consumer contract.

```bash
# No generation request: find literal model IDs that need review.
llm-preflight --audit-source . --json

# No generation request: validate config, credentials, selected models, tests,
# retry-expanded request count, and estimated cost.
llm-preflight benchmark.json --doctor --json
llm-preflight benchmark.json --tests agent-smoke --smoke --dry-run --json

# Paid request: run only after explicit authorization of the plan above.
llm-preflight benchmark.json --tests agent-smoke --smoke --json --no-save
```

Use `--migration-check` for a small current-versus-candidate compatibility
check, then run the task-specific contract tests that represent the affected
feature. `--smoke` is a low-cost compatibility signal, not a stable performance
ranking.

## Agent decision rules

An agent may:

- run `--audit-source` automatically to report literal model references;
- run `--doctor` and `--dry-run` automatically;
- report missing credentials, unknown pricing, invalid configuration, and
  failed validation with the command output; and
- prepare a proposed benchmark or CI change for review.

An agent must not:

- infer an unknown model provider or model ID;
- weaken a validator, schema, or expected result merely to make a run pass;
- start paid generation, increase a budget, or approve a model without an
  explicit instruction; or
- treat API success as application correctness when validation failed.

## CI handoff

Store a reviewed baseline and fail CI on configured regressions:

```bash
llm-preflight benchmark.json --tests agent-smoke --smoke --json --no-save > current.json
llm-preflight --diff baseline.json current.json --json --ci > comparison.json
```

The agent should attach the JSON evidence and a short explanation of any
failure. A successful comparison is a validation signal; model promotion and
production deployment remain separate approval steps.

## Prompt an agent can follow

> If you change any LLM model ID, provider call, prompt, tool definition,
> structured-output schema, validator, or parser, run LLM Preflight's no-spend
> checks. Preserve the deployed contract. Do not make paid requests, change a
> budget, weaken validation, or approve a model unless explicitly instructed.
> Report the dry-run plan and any validation evidence with your change.

For the full command and result contract, see the
[LLM and coding-agent guide](llm-guide.md).
