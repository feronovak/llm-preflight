# Troubleshooting

Start with the reported decision and blocking warnings. Diagnostic commands
below make no generation requests unless a section explicitly identifies a
provider call. Use the same Python environment and config path as the failing run.

## Installation fails with an externally managed environment

Create and activate a virtual environment before installing. In a new directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install llm-preflight
llm-preflight --version
```

The activation command is for POSIX shells; PowerShell uses
`.\.venv\Scripts\Activate.ps1`. If Python cannot create the environment, install
your operating system's Python venv support or use an existing managed Python
environment. Python 3.10 or newer is required.

## `catalog` is an unrecognized command

Your shell may be using an older installation. Activate the environment used
to run the tool, then upgrade the published package:

```bash
python3 -m pip install --upgrade llm-preflight
llm-preflight --version
llm-preflight catalog --help
```

If the module and console command disagree, compare
`python3 -m llm_preflight --version` with `llm-preflight --version`: the shell
may resolve a console script from another environment. For development from a
source checkout, use the separate [contributor setup](../../CONTRIBUTING.md).
Do not run `pip install .` from an arbitrary application directory.

## The local demo says PASS and then inconclusive

This is expected for the default mock. Its `ok` response passed the configured
exact-output rule; no live provider was tested, so the benchmark exits `3`.
A script should check that specific status for a known mock fixture. Do not
accept every nonzero exit or turn an inconclusive live run into a pass. Follow
[getting started](../getting-started/safe-demo.md) for the JSON example and next step.

## A live contract passes but the decision is inconclusive

Read every `decision.blocking_warnings` entry in the JSON. Missing usage,
unobserved retry usage, or unknown/stale pricing can prevent complete evidence.
A known subtotal is not a complete total. These checks help inspect the plan:

```bash
llm-preflight benchmark.json --doctor --json
llm-preflight benchmark.json --pricing-check
llm-preflight benchmark.json --dry-run --json
```

Replace `benchmark.json` with your actual config. Resolve missing evidence and
review the new bounds before authorizing another provider run. A diagnostic
pass does not change the saved run. See [pricing and safety](../guides/pricing-and-safety.md).

## Catalogue refresh says API keys are missing

The message lists missing key names and the `.env.production` file used by the
workspace. Configure the keys there or in the shell. To reuse a project file,
create the catalogue workspace beside it; `catalog init` links the existing
file instead of copying credentials. Do not paste key values into an issue.

## A workspace already exists

`catalog init` asks before changing discovery settings. Enter keeps the
workspace. Confirming rewrite preserves approved models, keys and saved results.

## A model returns HTTP 404

The model may be unavailable to this account, use the wrong endpoint, or be
retired. Inspect the exact provider/model/route with `--doctor --json` and the
[retirement evidence](../guides/retirements.md). A 404 alone does not prove
retirement. Do not approve the failed route; remove it from permanent state
with `models remove PROVIDER:MODEL --approved APPROVED` when applicable.

## The catalogue says “Needs one probe”

Provider metadata does not establish a usable request shape. For a model you
are considering, this **potentially billable** command asks for selection and
confirmation before sending one minimal request:

```bash
llm-preflight catalog probe benchmarks/watch.json
```

If you are not considering it, leave it alone. Image, audio, typed-decision
and other incompatible routes do not belong in the generic text suite.
Credential failure is not recorded as a model retirement. See the
[catalogue workflow](../guides/model-catalog.md).

## A model fails JSON or numeric validation

Distinguish an API error from a response that violates the declared rule.
Inspect the failed case, prompt and consumer parsing policy. Preserve the
validator unless the application contract itself is deliberately changing.
Prove accepted/rejected examples locally with `--contract-check` before
reviewing and authorizing a new live test. See [output contracts](../guides/output-contracts.md).

## I skipped approval or want to add a passing model later

Substitute the exact model ID and saved passing result. This changes local
approval state; it does not make a provider request:

```bash
llm-preflight models approve PROVIDER:MODEL --from RESULT.json --approved APPROVED.json
```

## I want to re-test approved models

`approved.json` is state, not a runnable benchmark config. Use
`catalog test WATCH.json --approved APPROVED.json --output approved-tests.json`
to build a plan. Preview with `llm-preflight approved-tests.json --dry-run`, then separately
review and authorize execution; an interactive run asks for confirmation.

## A benchmark is already running for this results folder

Only one benchmark can use an output folder at a time, preventing accidental
concurrent requests. Wait for the active run, or deliberately choose another
`--output-dir` for an independent run with its own authorized bounds.

## A local approval receipt is expired

An expiry is part of the review scope. Inspect a fresh dry-run plan and review
its bounds again before writing another receipt with a future timezone-qualified
time. Do not edit an old receipt to make it appear fresh. A receipt never
provides paid-run permission. See [change plans and receipts](../automation/change-plans.md).

## The merge gate says no_record or undecided

`no_record` means no matching record was supplied; a local fixture pass cannot
replace it. Ensure the protected producer workflow ran and the gate downloaded
its artifact. For `undecided`, read the exact reason code and `next` steps;
repository identity, invalid config or unreadable records need different fixes.
Use the [gate setup and reason codes](../guides/proof-of-preflight.md), and keep
signature verification separate. Do not weaken the gate to make a missing
record pass.
