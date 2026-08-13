# LLM and coding-agent guide

Use this tool to collect evidence for a model change. It validates explicit
output contracts, measures requests from the current host, and estimates cost.
It does not judge semantic quality or authorize a production rollout.

## Operating rules

1. Read the benchmark configuration before changing it. Preserve the deployed
   prompt, request settings, and validators unless the user explicitly asks to
   change the contract.
2. Run `--doctor` and `--dry-run` before a live benchmark. They make no
   generation requests.
3. Treat a validator failure as evidence, not a reason to weaken the validator.
   Inspect a saved response or add an explicitly approved contract change.
4. Do not infer a provider for an unknown model ID. Use explicit
   `provider:model` syntax, especially with `--quick`.
5. Do not approve a model, raise a spend limit, or start a paid run without an
   explicit instruction. Unknown pricing is not zero cost.

## Optional repository instruction block

To add these rules to a repository without replacing its own instructions, opt
in explicitly when initializing a benchmark:

```bash
llm-preflight init benchmark.json --agent-instructions AGENTS.md
```

The command manages only its marker-delimited block. It never enables this by
default, preserves user content outside the markers, and refuses a symbolic-link
target. Check committed instructions in CI without changing files:

```bash
llm-preflight init --agent-instructions AGENTS.md --check
```

The managed `v1` content is intentionally kept in sync with the CLI:

```markdown
<!-- llm-preflight:agent-instructions:v1:start -->
## LLM preflight operating rules

Before changing a model ID, provider call, prompt, parser, or tool definition:

1. Read the benchmark configuration and preserve the deployed contract unless a
   contract change is explicitly approved.
2. Run `--doctor` and `--dry-run` before any live benchmark.
3. Treat a validator failure as evidence, not a reason to weaken the validator.
   Inspect a saved response or make an explicitly approved contract change.
4. Do not infer a provider for an unknown model ID; use `provider:model`.
5. Do not approve a model, raise a spend limit, or start paid work without
   explicit user approval.
6. Surface every `blocking_warnings` entry verbatim, then run
   `llm-preflight CONFIG --doctor --json` before paid work or approval.

This block is managed by `llm-preflight init --agent-instructions PATH`.
<!-- llm-preflight:agent-instructions:v1:end -->
```

## Safe command sequence

Start with the recommended `agent-smoke` suite: strict JSON extraction,
support classification, code-patch summary, source-grounded quiz, and refusal
boundary. It is production-shaped and excludes load testing.

```bash
# Validate configuration, available credentials, and model resolution.
llm-preflight benchmark.json --doctor --json

# Inspect exact models, tests, retry-expanded request count, and estimated cost.
llm-preflight benchmark.json --tests agent-smoke --smoke --dry-run --json

# Make paid requests only after the plan is accepted.
llm-preflight benchmark.json --tests agent-smoke --smoke --json --no-save
```

`--smoke` means one repetition, no warmups, and concurrency one. It is a
low-cost compatibility check, not a performance ranking. Use task-specific
tests and more repetitions before a consequential model switch.

Interactive mode provides the same safeguards in the terminal:

```bash
llm-preflight benchmark.json --interactive
```

Select `agent-smoke` at the test prompt unless a different reviewed contract is
needed. The run-plan screen and its separate `y` confirmation are the point at
which a paid request becomes authorized.

## Configuration contract

Keep the config close to the consumer's actual contract. This minimal example
expects a raw JSON object with a known routing label and caps output:

```json
{
  "prompt": "Classify this support request. Return JSON only.",
  "models": [{"provider": "openai", "model": "your-reviewed-model"}],
  "request": {"temperature": 0, "max_output_tokens": 256},
  "validation": {
    "json_schema": {
      "type": "object",
      "required": ["route"],
      "properties": {
        "route": {"type": "string", "enum": ["billing", "technical", "account"]}
      }
    }
  },
  "max_requests": 12
}
```

Use `allow_fenced_json` only if the real consumer accepts exactly one complete
Markdown-fenced JSON block. Do not enable it merely because a model returned
fences during a preflight. See [Configuration reference](../reference/configuration-schema.md)
for all validation and pricing fields. Add `max_estimated_cost_usd` only after
every selected model has known pricing (or an explicit reviewed price); an
unknown price cannot safely enforce a cost ceiling.

## Read results correctly

For the normal benchmark, `--json` writes one JSON document to stdout. Status
and saved-result notices go to stderr. With `--baseline BASELINE --json`, the
comparison is included in `baseline_diff` in that same JSON document.

Key distinctions:

- `success_rate` means requests completed successfully.
- `valid_output_rate` means completed responses met the configured contract.
- A response can have API success but fail validation; it is not a passing
  model result.
- Cost is an estimate from known pricing and reported usage. Cached input,
  reasoning output where the provider reports it, and configured pricing tiers
  are included. Unknown pricing remains unknown.

Read `decision` before acting. `pass` is complete passing evidence; `fail` is
evidence of a request or contract failure and takes precedence over degraded
evidence; `inconclusive` means no hard failure was observed but the evidence is
degraded by unknown/stale pricing, incomplete cost evidence, or a mock-only
run. Cost confidence is blocking only for runs with billable routes; retries
remain informational. Surface every `blocking_warnings` entry
verbatim, then run `llm-preflight CONFIG --doctor --json` before paid work or
approval. See [Agent decision contract](../reference/decision.md).

Exit codes are `0` for a passing requested operation, `1` for benchmark or CI
failure, `2` for invalid input or operational setup error, and `130` for a
cancelled run.

## Automation pattern

Keep a reviewed baseline and compare a separately saved current result:

```bash
llm-preflight benchmark.json --tests agent-smoke --smoke --json --no-save > current.json
llm-preflight --diff baseline.json current.json --json --ci > comparison.json
```

The comparison gate retains defaults for any threshold not explicitly
overridden. Missing validation evidence or a model removed from the current run
fails the comparison. Keep catalog discovery and new-model approval separate
from a benchmark gate; discovery is not compatibility evidence, and a passing
run is not approval unless a user explicitly records it.
