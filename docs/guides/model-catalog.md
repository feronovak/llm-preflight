# Model catalogue: discover, test, and keep models

**Last reviewed:** 2026-08-31 · **As of:** v2.8.0

Use the catalogue when you want a small, trusted list of models for your own
work. It is deliberately a local workflow: provider catalogues are broad;
your approved list contains only models you chose after testing.

```text
provider metadata → price check → probe → bounded smoke → human approval → re-test
```

You do not need to edit the catalogue files by hand. Commands create and update
them for you. Discovery reads metadata only; a probe or benchmark is the point
where a provider may charge for a request.

## The four files, in plain English

Run this once in an empty project directory:

```bash
llm-preflight catalog init
```

Press Enter to include all supported providers. The command creates:

```text
benchmarks/
├── watch.json       # what to discover and how candidate tests should run
├── approved.json    # models you deliberately keep
├── candidates.json  # temporary test plan; created later
├── results/         # saved benchmark evidence
└── .llm-preflight/  # automatic catalogue snapshots and probe evidence
```

Keep API keys in `benchmarks/.env.production`, never in JSON or Git. If your
project already has a neighbouring `.env.production`, setup reuses it rather
than copying keys. `catalog init` asks before changing an existing workspace.

## First time: choose models without guessing

### 1. Refresh the provider catalogues

```bash
llm-preflight catalog refresh benchmarks/watch.json
```

This makes metadata requests only. It tells you what changed since the last
refresh; `Added: 0` simply means the provider IDs did not change. It does not
mean there are no models, and it never sends your benchmark prompt.

Each discovered model is placed in one of three useful groups:

| Group | Meaning | What you do |
|---|---|---|
| **Ready to review for smoke** | Provider metadata, or a previous successful probe, identifies a supported text adapter. | Check current pricing and declared bounds in the dry-run before selecting it. |
| **Needs one probe** | It looks like a text model but metadata cannot safely prove the request shape. | Optionally make one small, provider-native request. |
| **Not a generic text benchmark model** | It is image, audio, video, realtime, agent, or another incompatible endpoint. | Leave it out of a normal text suite. |

The third group remains visible. It is not silently deleted or treated as a
failed chat model. Refresh also returns `smoke_eligibility` in JSON: every
model is either `eligible` or has one stable reason explaining the next review
step. A model can be text-ready yet still need pricing, declared limits, or
adapter evidence before it is eligible for a paid smoke.

### 2. Probe only the text candidates you care about

If refresh reports **Needs one probe**, review those models first:

```bash
llm-preflight catalog probe benchmarks/watch.json
```

Select one or a few model numbers, then confirm. The probe sends one minimal
request and may be billable. It stores no response text—only the outcome,
adapter, safe request settings, and a provider fingerprint when available.
Successful models become **Ready to benchmark** locally. When the provider
supplies a fingerprint (currently xAI), a change expires that evidence and asks
for a new probe; providers without one keep their evidence until you probe
again.

Do not probe everything merely because it is listed. Use it for models you are
actually considering. Account access, regions, and provider rollouts can make a
model available to one user and unavailable to another.

### 3. Make a temporary candidate plan and inspect its evidence

```bash
llm-preflight catalog prepare benchmarks/watch.json \
  --against benchmarks/approved.json \
  --output benchmarks/candidates.json
```

The selector shows only **Ready to review for smoke** models. Pick the few models you
want to compare; `all` means all displayed compatible text models, never every
ID in every provider catalogue. The resulting `candidates.json` is temporary.
It does not change your approved list or authorize a request. Preview the exact
selection before any paid work:

```bash
llm-preflight benchmarks/candidates.json --migration-check --smoke --dry-run --json
```

Read `smoke_eligibility.models[]` before authorizing a run. Only an
`eligible: true` row has compatible text type, provider-adapter evidence,
current pricing, and both a request and cost bound. The stable reasons are:

| Reason | Required next step |
|---|---|
| `catalog_evidence_required` | Discover through a supported catalogue or add reviewed catalogue evidence. |
| `probe_required` | Explicitly run one minimal `catalog probe` request for the selected text candidate. |
| `adapter_evidence_required` | Retain compatible provider-adapter evidence; do not guess a request shape. |
| `incompatible_catalog_type` | Keep it out of the generic text smoke cohort. |
| `unknown_pricing`, `undated_pricing`, `stale_pricing` | Review the direct-provider price evidence. |
| `bounded_limits_required` | Declare both `max_requests` and `max_estimated_cost_usd`. |

Do not change a reason by editing a result. Fix the evidence in the candidate
configuration or local probe ledger, then preview again.

`catalog prepare` writes only rows that are already smoke-eligible; models
needing a probe, price review, catalogue/adapter evidence, or bounds remain in
the refresh output rather than being smuggled into a runnable candidate file.
Eligibility confirms that both caps are declared; immediately before any paid
catalog run, the existing budget gate recalculates the retry-expanded request
count and maximum estimated cost and refuses a plan that exceeds either cap.

If you intentionally want a fresh temporary plan, make replacement explicit:

```bash
llm-preflight catalog prepare benchmarks/watch.json \
  --against benchmarks/approved.json \
  --output benchmarks/candidates.json --replace
```

### 4. Run the response-and-contract comparison

Start with the three-case migration check. It makes the smallest useful paid
comparison: can each model respond through your account, meet a basic response
contract, and respond quickly enough from this host?

```bash
llm-preflight benchmarks/candidates.json --migration-check --dry-run
llm-preflight benchmarks/candidates.json --migration-check \
  --output-dir benchmarks/results
```

Then use interactive mode for the task-specific contract that matters to your
application—for example structured output or exact routing:

```bash
llm-preflight benchmarks/candidates.json --interactive \
  --approve-to benchmarks/approved.json \
  --output-dir benchmarks/results
```

Interactive mode has one clear job: select the benchmark work, preview its
maximum request count and estimated cost, then confirm the run. A compatibility
screen with one repetition answers “does this model work for this suite?” It is
not enough evidence for a stable latency ranking. See [Interactive mode](interactive-runs.md).

### 5. Keep only passing models

At the end, the command lists passing models that are not already approved.
Choose the ones you want, confirm, and they are added to `approved.json` with
the saved result as evidence. Skipping a model is fine: it remains only in the
result history, not in your permanent set.

To promote a passing model later, use its saved result:

```bash
llm-preflight models approve openai:MODEL_ID \
  --from benchmarks/results/RUN.json \
  --approved benchmarks/approved.json \
  --note "Passed our candidate review."
```

## Routine maintenance

### A provider announces a model

Repeat this short loop:

```text
refresh → price check → probe only candidates you want → bounded smoke → contract test → approve
```

Existing approvals do not change during discovery. If a selected model returns
404, it is not available to your account or has been retired; do not approve it.

### Re-test the models you already use

`approved.json` is a record of decisions, not a runnable benchmark. Build a
test plan from it, then run that plan:

```bash
llm-preflight catalog test benchmarks/watch.json \
  --approved benchmarks/approved.json \
  --output benchmarks/approved-tests.json
llm-preflight benchmarks/approved-tests.json --interactive \
  --output-dir benchmarks/results
```

Use the tests that resemble your workload. For a performance conclusion, use
several repetitions from the same host; one repetition is a cheap compatibility
check only.

### Remove a model you no longer want

```bash
llm-preflight models remove PROVIDER:MODEL_ID \
  --approved benchmarks/approved.json \
  --note "Retired by provider."
```

The command confirms the change and preserves old result files as history.

## Useful checks

Before any paid run, inspect it without sending requests:

```bash
llm-preflight benchmarks/candidates.json --dry-run
llm-preflight benchmarks/candidates.json --pricing-check
```

Unknown pricing is shown as `n/a`, not free. Keep `max_requests` and, where
pricing is complete, `max_estimated_cost_usd` in `watch.json` to limit risk.

For the complete command forms, see the [CLI reference](../reference/cli.md). For
common problems, see [Troubleshooting](../operations/troubleshooting.md).

`watch-new` and `approve-model` remain compatibility aliases for older scripts.
Use the `catalog` and `models` commands in new work.
