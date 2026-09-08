# Git-aware change plans

**Last reviewed:** 2026-09-04 · **As of:** v2.12.0

Use a change plan after an agent or engineer edits an LLM integration and before
the ordinary no-spend checks:

```bash
llm-preflight benchmark.json --change-plan HEAD --json
```

The command compares the current worktree with `HEAD` (or the supplied Git
reference), includes modified, staged, deleted, and untracked files, and reports literal model IDs
plus likely prompt, validation, schema, tool, or provider-option surfaces. It
uses Git argument arrays, does not execute project code, load credentials,
contact providers, or authorize paid work.

Its findings are deliberately incomplete: dynamic model selection and generated
prompts require human review. Treat the recommended `--doctor`, optional
`--contract-check`, and `--dry-run` commands as the next no-spend steps, not as
approval for a live benchmark.

## Record a bounded review

After a person reviews a dry-run, they can preserve the decision locally:

```bash
llm-preflight benchmark.json --dry-run --no-env-file \
  --approval-receipt .llm-preflight/approvals/checkout.json \
  --approval-note "Reviewed checkout smoke." \
  --approval-expires-at 2026-09-05T12:00:00+00:00 --json
```

Receipts are owner-only local JSON files. They contain the plan hash, expiry,
review note, and retry-expanded request/cost bounds. Verify one against a fresh
dry-run before discussing it:

```bash
llm-preflight benchmark.json --dry-run --no-env-file \
  --verify-approval-receipt .llm-preflight/approvals/checkout.json --json
```

A receipt is audit evidence only. It never raises a cap, promotes a model, or
authorizes a provider call; explicit user approval remains required at runtime.
