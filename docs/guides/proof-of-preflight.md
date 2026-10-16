# Proof of preflight: the record and the merge gate

**Last reviewed:** 2026-10-17 · **As of:** unreleased source

A pull request that changes an LLM contract should not merge on a stale,
borrowed or hand-typed pass. Proof of preflight is three commands: `attest`
writes a record that a bounded check ran, `verify` reports whether a record is
intact and still fresh, and `gate` decides whether the current tree has a
fresh, passing record from CI.

It doesn't certify production behaviour. It proves the check was done.

## What a record proves

Before takeoff, the pilot signs the preflight check. The signature does not
promise a safe flight; it proves the check was done, on that aircraft, that
day. A preflight record works the same way: it proves that this contract
passed on these routes, on a stated day, in a named CI run.

A record states:

- which contract and routes were checked, as SHA-256 fingerprints of the
  configuration's contract and its resolved provider routes, with the pricing
  and evidence fingerprints;
- the decision of that run, copied and never upgraded: `PASSED`, `WARNED`
  (inconclusive) or `FAILED`, with the test names behind it;
- the run's selection flags (`--prompt`, `--tests`, `--env`,
  `--migration-check`), by name only, and the model each provider reported
  answering, or none when its responses named none;
- when the run happened, how many requests it made, its cost and how
  complete that cost is;
- in GitHub Actions, the repository, workflow, run, attempt and commit.

A record does not prove production behaviour, accuracy beyond the declared
validators, safety, or behaviour on other accounts or regions; it lists these
under `claimsNotMade`. On its own it does not prove who wrote it either:
anyone can write JSON. That is why the gate never accepts a committed record,
never passes one without a CI run identity, and why public repositories
should sign it. The record is an
[in-toto Statement](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
with the
[test-result predicate](https://github.com/in-toto/attestation/blob/main/spec/predicates/test-result.md);
[Preflight record](../reference/results.md#preflight-record) lists every
field.

## The three commands

```bash
llm-preflight attest results/run.json
llm-preflight verify results/run.preflight.json
llm-preflight gate benchmark.json --repository acme/app --records records
```

`attest` reads a saved result and its configuration and writes
`results/run.preflight.json`. It refuses a result without schema-version-1
provenance and never turns an inconclusive run into a pass. In GitHub Actions
it records the run identity; anywhere else the record says `local`.

`verify` reports integrity (the record's shape, its fingerprints and its
internal consistency) and freshness (its age and the retirement status of its
routes) separately. It exits 0 when the record is intact and fresh, 1 when its
integrity is broken, and 3 when it is intact but stale or superseded. It does
not check signatures; `gh attestation verify` does.

`gate` fingerprints the current configuration offline, with no credentials and
no provider request, and reads every record file given, searching
directories for `*.preflight.json`. It passes only on the newest CI record
from this repository that ran the same selection, matches the current
contract and routes and is `PASSED`, consistent, fresh and not superseded. It
exits 0 on a pass, 1 when blocked and 3 when it cannot decide. Fetching
records is the workflow's job, never the gate's.

To show a record to people, render its card:

```bash
llm-preflight report results/run.json --format svg \
  --record results/run.preflight.json --output card.svg
```

The [preflight card](reports.md#preflight-card) is generated from the
evidence and is not evidence itself.

## Same selection, same repository

The gate sets the bar; a record cannot lower it. Call the gate with the same
selection flags as the run that wrote the record: `--prompt NAME`,
`--tests LIST` (or its alias `--profiles`), `--env NAME` and
`--migration-check`. Without them the gate requires a default run. It
fingerprints the configuration as a run under those flags would, and a record
that ran another selection, such as one cheap `--tests` choice where the gate
requires a default run, is blocked as `selection_changed`. A result written
before 2.22.0 records no selection, so its record is blocked the same way.
`--smoke`, `--env-file` and `--no-save` are not selections: smoke mode changes
how many requests run, not the contract, and an env file only supplies
credentials. The
[Marketplace Action](../automation/github-action.md#proof-of-preflight) runs a
default smoke, so a gate for its records takes no selection flags.

Only records from this repository count, because another repository's record
can carry the same fingerprints. The gate takes the repository from
`--repository OWNER/NAME`, else from `GITHUB_REPOSITORY` on
`GITHUB_SERVER_URL` (default `https://github.com`), which GitHub Actions sets
in every job. Owner, name and host are compared without regard to case, as
GitHub does. A record from elsewhere is blocked as `foreign_record`. Outside
CI, give `--repository`; without any repository the gate cannot decide
(`repository_unknown`, exit 3).

## Gate reason codes

Every gate decision carries one reason code, in the text output and as
`reason_code` in `--json`:

| Code | Decision | Exit | Meaning |
|---|---|---:|---|
| `fresh_pass` | pass | 0 | The newest matching CI record is `PASSED`, consistent, fresh and not superseded. |
| `no_record` | blocked | 1 | No record was found in the paths given. |
| `foreign_record` | blocked | 1 | No record comes from this repository and server; another repository's pass proves nothing here. |
| `selection_changed` | blocked | 1 | No record ran the selection the gate requires, or the record predates selections; both selections are named. |
| `contract_changed` | blocked | 1 | No record checked the current contract: its `validation`, validation fixtures, `prompts` entries, tools, test profiles or the validator version changed. The top-level `prompt` is not part of the contract fingerprint. |
| `routes_changed` | blocked | 1 | No record checked the current provider routes. |
| `stale` | blocked | 1 | The newest matching record is older than `--max-age-days` (default 30). |
| `superseded` | blocked | 1 | A route the newest matching record checked has since retired, per this verifier's bundled retirement snapshot. |
| `inconclusive_record` | blocked | 1 | The newest matching record is `WARNED`; an inconclusive run never passes. |
| `failed_record` | blocked | 1 | The newest matching record is `FAILED`. |
| `inconsistent_record` | blocked | 1 | A record fails its integrity check, and no intact record matches. |
| `committed_record` | blocked | 1 | The record is tracked by Git. A committed record can be hand-typed, so the gate never accepts one. |
| `local_record` | blocked | 1 | The record has no CI run identity. |
| `record_error` | cannot decide | 3 | A record path is missing, unreadable or not JSON; the gate cannot decide without every record it was given. |
| `config_error` | cannot decide | 3 | The configuration cannot be fingerprinted offline, for example because its routes come from catalogue discovery. |
| `repository_unknown` | cannot decide | 3 | Neither `--repository` nor `GITHUB_REPOSITORY` names this tree's repository. |

The gate decides on the newest record from this repository that ran the
required selection and matches the current contract and routes, whatever its
verdict, so an older pass cannot hide a newer failure; on equal age, the
failure wins. Only when no record matches does it explain the block with the
first applicable code among `committed_record`, `local_record`,
`foreign_record`, `inconsistent_record`, `selection_changed`,
`contract_changed` and `routes_changed`.

## Private and public repositories

Every repository can use the unsigned flow. The
[Marketplace Action](../automation/github-action.md#proof-of-preflight) with
`attest: "true"` writes the record after an approved paid smoke and uploads it,
with its card, as the `llm-preflight-record` artifact. The result itself,
which holds the prompts, is not uploaded. The pull-request workflow in
[CI and JSON output](../automation/ci.md#proof-of-preflight-gate) downloads
the newest record from that workflow's runs and runs the gate. The gate accepts
the record because it is not committed and carries a CI run identity; it does
not check who started the run, so keep the paid workflow on protected branches
and behind a reviewed environment.

Public repositories, and private or internal ones on GitHub Enterprise Cloud,
can also sign the record. `sign: "true"` passes it to `actions/attest`, which
signs it with Sigstore through GitHub's artifact attestations. The calling job
needs `id-token: write` and `attestations: write`. `gh attestation verify` then
checks that a workflow of this repository produced exactly these bytes; run it
before the gate, because the gate itself does not check signatures. On other
private repositories GitHub does not offer artifact attestations, so the
record stays unsigned and the CI artifact is the evidence.

## Freshness

A record stays fresh for 30 days after its run: `valid_until` is the check's
date plus 30 days, and the record is fresh through that day. After it, the gate
reports `stale`, `verify` exits 3 and the card turns EXPIRED. `--max-age-days`
shortens or lengthens the window for one gate or verify call.

A route that retires supersedes the record on its retirement date, whatever
its age. The verifier judges this with its own bundled retirement snapshot, not
the one the record was written with, and prints that snapshot's date.

A monthly refresh on the 1st leaves a gap after 31-day months; a run on the
1st and 15th keeps a record within 30 days. Each scheduled run is paid work,
so bound it like any other paid smoke.

## When the gate blocks

Read the `Why:` line, then follow the numbered `Next:` steps; they never
include a paid request without a dry-run first. The common cases:

1. `contract_changed` or `routes_changed`: the pull request changed what the
   record checked, which is the gate working. Review the plan with
   `llm-preflight benchmark.json --dry-run`, approve it, then run the record
   workflow on the pull request's branch; the gate workflow looks for that
   branch's record before `main`'s.
2. `stale` or `superseded`: run the bounded check again. For a retired route,
   move to the replacement the dry-run names first.
3. `inconclusive_record` or `failed_record`: run `llm-preflight verify` on the
   record to see the blocking warnings or failed tests, fix them, and run the
   bounded check again.
4. `selection_changed`: give the gate the selection flags of the run CI
   makes, or run CI with the selection the gate requires; the `Why:` line
   names both. A result from before 2.22.0 needs a new run.
5. `committed_record`: remove the record from Git
   (`git rm --cached FILE`), add `*.preflight.json` to `.gitignore`, and let CI
   attest each run.
6. `local_record` or `foreign_record`: run the bounded check in this
   repository's CI, where the record gets this repository's run identity.
7. `record_error` or `config_error`: fix the file the gate names; the
   `--doctor` check reads the configuration for free.
8. `repository_unknown`: outside GitHub Actions, add
   `--repository OWNER/NAME` for the repository the tree belongs to.

Never make the gate pass by editing a record or the workflow. If the check
cannot pass for a reason you accept, say so in the pull request and let a
person decide.
