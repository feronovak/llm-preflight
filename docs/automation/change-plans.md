# Git-aware change plans

**Last reviewed:** 2026-10-19 · **As of:** v2.22.1

Use a change plan after an agent or engineer edits an LLM integration and before
the ordinary no-spend checks:

```bash
llm-preflight benchmark.json --change-plan HEAD --json
```

The command compares the current worktree with `HEAD` (or the supplied Git
reference), includes modified, staged, deleted, and untracked files, and reports literal model IDs
plus likely prompt, validation, schema, tool, or provider-option surfaces. It
uses Git argument arrays, does not execute project code, load credentials,
contact providers, or authorize paid work. Git runs with the repository's
hooks, file-system monitor, filter drivers and object fetching disabled, and
does not look inside submodules for uncommitted edits: a submodule is listed
when its recorded commit changes. Files inside an untracked nested
repository are not inspected. A repository whose filter driver name
contains `=` cannot have that driver disabled, so the change plan refuses it.

Before 2.24.0, a changed file the command may not read stopped the plan with an error.

A changed file the command cannot read does not stop the plan. That covers no
read permission, a directory it may not enter, a symlink loop, and a file that
is not UTF-8 text where `--audit-source` would read it (its source suffixes,
for example a UTF-16 `.py` prompt). A non-UTF-8 file with any other suffix, an
image or a UTF-16 `prompt.txt` for example, is not counted. A prompt in such a
file is not flagged, so `plan_incomplete: false` does not mean every changed
file was read.
The JSON `change_plan` object reports `files_unreadable` (a count, named as in
`--audit-source`), `unreadable_files` (the paths), and `plan_incomplete`
(`true` when any file was unreadable). A path Git lists as deleted but the
command may not look at is reported as unreadable, not as deleted. A directory
Git could not open is listed with a trailing `/`, because the files in it were
not listed. The plan does not treat a file it counted as unreadable as touching no
model ID, prompt, schema or tool definition, so `requires_preflight_review` is
also `true`, and the first note says the plan is incomplete. The text output
prints the same sentence and the paths. A deleted file is read from the Git
reference, and a staged file is read from the index as well as the work tree;
triggers from either carry `change` set to `deleted` or `staged`.

Its findings are deliberately incomplete: dynamic model selection and generated
prompts require human review. Treat the recommended `--doctor`, optional
`--contract-check`, and `--dry-run` commands as the next no-spend steps, not as
approval for a live benchmark.

## Record a bounded review

After a person reviews a dry-run, they can preserve the decision locally:

The example below expires one hour from now; choose a duration matching the
reviewed plan. The timestamp is computed, not a historical date to copy.

```bash
receipt_expires_at=$(python3 -c 'from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())')
llm-preflight benchmark.json --dry-run --no-env-file \
  --approval-receipt .llm-preflight/approvals/checkout.json \
  --approval-note "Reviewed checkout smoke." \
  --approval-expires-at "$receipt_expires_at" --json
```

Receipts are owner-only local JSON files. They contain the plan hash, expiry,
review note, and retry-expanded request/cost bounds. Verify one against a fresh
dry-run before discussing it:

```bash
llm-preflight benchmark.json --dry-run --no-env-file \
  --verify-approval-receipt .llm-preflight/approvals/checkout.json --json
```

A receipt is audit evidence only. It never raises a cap, promotes a model, or
authorizes a provider call. It is a required precondition of `migrate --run`, which is itself the authorizing act; the receipt alone starts nothing. A direct CLI run does not check a receipt or ask
for separate approval; authorize the reviewed plan before invoking it.
