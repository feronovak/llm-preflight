---
name: llm-preflight
description: Prepare and interpret local LLM integration preflights when a model, provider, prompt, schema, parser, or tool definition changes. Do not use for broad statistical evaluations or production observability.
---

# LLM Preflight

Use the local MCP server or CLI to gather evidence for an LLM integration
change. Keep the benchmark contract specific to the application change.

1. Use `validate_config` after the change.
2. Use `dry_run_plan`; report the request bound, estimated cost, pricing
   coverage, and every non-eligible smoke reason.
3. Stop before live provider traffic. You must not infer approval from a
   configuration, a dry-run, a tool call, or a previous result.
4. Run a live preflight only after an explicit user instruction and only with
   `confirm_paid_run: true`. Preserve the returned structured `decision` and
   its blocking warnings.

Mock runs, validation, planning, and baseline diffs do not contact providers.
Do not approve a model, raise a budget, weaken the contract, or treat a pass as
production approval. See `docs/automation/mcp.md` and
`docs/reference/decision.md` in the project for the complete contract.
