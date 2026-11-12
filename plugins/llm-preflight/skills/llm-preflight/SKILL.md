---
name: llm-preflight
description: Prepare and interpret local LLM integration preflights when a model, provider, prompt, schema, parser, or tool definition changes. Do not use for broad statistical evaluations or production observability.
---

# LLM Preflight

Use the local MCP server or CLI to gather evidence for an LLM integration
change. Keep the benchmark contract specific to the application change.

In a repository with no benchmark config, use `audit_source` first. It needs
no config and makes no provider request. Report its `decision` before anything
else: `fail` means a referenced model is retired, `inconclusive` means one is
retiring, its snapshot row is stale, it is an alias without a safe mapping to
one snapshot row (`alias_unmapped`), or no file was read, `pass` means every
referenced model the snapshot lists is active, and `none` means no reference
is in the retirement snapshot; it is not a pass. Report
`retirement_snapshot.valid_until`, the last day before the oldest bundled row
turns stale. It covers only literal model IDs; a model chosen at run time needs
review. `ok` does not reflect it. Then follow the
[project integration guide](https://github.com/feronovak/llm-preflight/blob/main/docs/getting-started/project-integration.md)
to create a benchmark; the other MCP tools read an existing config and do not
create it.

1. Use `validate_config` after the change.
2. Use `dry_run_plan`; report the request bound, estimated cost, pricing
   coverage, every non-eligible smoke reason, and the `retirements` decision:
   `fail` means a selected model is retired, `inconclusive` means one is
   retiring, its snapshot row is stale, or it is an `alias_unmapped`. `ok` does
   not reflect it. `ok: false` means the plan breaks a limit: report
   `budget_limits.violations` (a request or cost cap, or incomplete pricing
   under `require_current_pricing`); a live run refuses with the same message.
   Report `retirements.snapshot.valid_until` with it: after that day the
   selected models' snapshot rows are stale and the decision turns
   `inconclusive`; it is absent when no selected model has a non-retired row.
   Report `pricing_warnings` too, including `owner_price_ignored`: an owner
   price the bundled snapshot replaced, so the cost figure is not the owner's.
3. Stop before live provider traffic. You must not infer approval from a
   configuration, a dry-run, a tool call, or a previous result.
4. Run a live preflight only after an explicit user instruction and only with
   `confirm_paid_run: true`. Preserve the returned structured `decision` and
   its blocking warnings.

To check proof of preflight, use `verify` on a record CI attested, or `gate`
with the config, the downloaded records and the selection CI runs, `smoke`
included. Report the
gate's `decision`, `why` and next steps verbatim. A gate `pass` is not
approval: it shows that a fresh passing CI record matches the contract, never
that a model, a budget, a merge or paid work is approved. Never attest a
record yourself; that stays a CI step.

Source audits, mock runs, validation, planning, baseline diffs, `verify` and
`gate` do not contact providers.
Do not approve a model, raise a budget, weaken the contract, or treat a pass as
production approval. See `docs/automation/mcp.md` and
`docs/reference/decision.md` in the project for the complete contract.
