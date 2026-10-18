# Proof of preflight: the record and the merge gate

**Last reviewed:** 2026-10-17 · **As of:** v2.22.0

Proof of preflight lets a required check block a pull request that changes an
LLM contract until a fresh, passing check of that contract ran in this
repository's CI. It is three commands: `attest` writes a record that a bounded
check ran, `verify` reports whether a record is intact and still fresh, and
`gate` decides whether the current tree has a fresh, passing record from CI.

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
- every prompt the run sent, with fingerprints of its text and of the request
  options sent with it: the system prompt, temperature, token limit,
  reasoning effort, provider options, expanded presets, and each input image
  by its content, not its path;
- the decision of that run, copied and never upgraded: `PASSED`, `WARNED`
  (inconclusive) or `FAILED`, with the test names behind it;
- the run's selection flags (`--prompt`, `--tests`, `--env`,
  `--migration-check`, `--smoke`), by name only, how many times it sent each
  prompt, and the model each provider reported answering, or none when its
  responses named none;
- when the run happened, how many requests it made, its cost and how
  complete that cost is;
- in GitHub Actions, the repository, workflow, run, attempt and commit of the
  run that made the result, read when the run started.

A record does not prove production behaviour, accuracy beyond the declared
validators, safety, or behaviour on other accounts or regions; it lists these
under `claimsNotMade`. On its own it does not prove who wrote it either:
anyone can write JSON, and a record is only as trustworthy as the workflow
that produced it. That is why the gate never accepts a committed record,
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
provenance and never turns an inconclusive run into a pass. The run writes
its GitHub Actions identity into the result when it starts, and `attest`
copies it only when it runs in that same run (same repository, server, run
and commit). Anywhere else, including a later job or a laptop, the record
says `local` and `attest` prints why.

`verify` reports integrity (the record's shape, its fingerprints, its
internal consistency, and whether the config and result files it names still
match their digests) and freshness (its age and the retirement status of its
routes) separately. It exits 0 when the record is intact and fresh, 1 when its
integrity is broken, and 3 when it is intact but stale or superseded. It does
not check signatures; `gh attestation verify` does.

`gate` fingerprints the current configuration offline, with no credentials and
no provider request, and reads every record file given, searching
directories for `*.preflight.json`. It passes only on the newest CI record
from this repository that ran the same selection, matches the current
contract, routes and prompts, and is `PASSED`, consistent, fresh and not
superseded. It judges a record by its internal consistency only and never
reads the config or result file a record names: those come from the pull
request's tree, which must not decide which record counts. It exits 0 on a
pass, 1 when blocked and 3 when it cannot decide. Fetching records is the
workflow's job, never the gate's.

To show a record to people, render its card:

```bash
llm-preflight report results/run.json --format svg \
  --record results/run.preflight.json --output card.svg
```

The [preflight card](reports.md#preflight-card) is generated from the
evidence and is not evidence itself.

## Same selection, same repository

The gate names the selection, and only a record that ran exactly that
selection counts. Call the gate with the same selection flags as the run that
wrote the record: `--prompt NAME`, `--tests LIST` (or its alias
`--profiles`), `--env NAME`, `--migration-check` and `--smoke`. Without them
the gate requires a default run. It fingerprints the configuration as a run
under those flags would, including how many times that run sends each prompt.
The comparison is a hash of the raw selection, stored before the result is
redacted. Credential-keyed values are masked and every other word is kept, so
prompt names that differ only by a word such as `sk-alpha` and `sk-beta` do
not match. A record without that hash is blocked. `attest` copies the hash,
the decision state, the blocking warnings and the cost confidence into the
record's sealed provenance. `verify` rejects a record whose annotations
disagree with that seal, so editing them without recomputing the checksum
fails integrity. The seal is a checksum of those fields, not a signature,
and it does not cover `checkedAt`: anyone who edits a record can reseal it.
Only a signature checked with `gh attestation verify` stops a resealed
record.
A record that ran another selection, such as one cheap `--tests` choice or a
`--smoke` run where the gate requires a default run, or fewer repetitions per
prompt than the configuration now asks for, is blocked as
`selection_changed`. So a record cannot lower the bar by running less; a
record that ran more, or something else, does not count either. A result
written before 2.22.0 records no selection, so its record is blocked the same
way. `--env-file` and `--no-save` are not selections: an env file only
supplies credentials. The
[Marketplace Action](../automation/github-action.md#proof-of-preflight) runs a
default `--smoke`, so a gate for its records takes `--smoke`.

Only records from this repository count, because another repository's record
can carry the same fingerprints. The gate takes the repository from
`--repository OWNER/NAME`, else from `GITHUB_REPOSITORY` on
`GITHUB_SERVER_URL` (default `https://github.com`), which GitHub Actions sets
in every job. Owner, name and host are compared without regard to case, as
GitHub does. A record from elsewhere is blocked as `foreign_record`. Outside
CI, give `--repository`; without any repository, or when `--repository` and
`GITHUB_REPOSITORY` name different repositories, the gate cannot decide
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
| `contract_changed` | blocked | 1 | No record checked the current contract: its `validation`, validation fixtures, `prompts` entries, tools, test profiles or the validator version changed. |
| `routes_changed` | blocked | 1 | No record checked the current provider routes. |
| `prompt_changed` | blocked | 1 | No record checked the prompts sent now: the text of a prompt, including the top-level `prompt`, or the request options sent with it changed, or a prompt was added or removed. The `Why:` line names the prompt and whether its text or its request options changed. A record from before 2.22.0 has no request fingerprints and is blocked the same way. |
| `stale` | blocked | 1 | The newest matching record is older than `--max-age-days` (default 30). |
| `superseded` | blocked | 1 | A route the newest matching record checked has since retired, per this verifier's bundled retirement snapshot. |
| `inconclusive_record` | blocked | 1 | The newest matching record is `WARNED`; an inconclusive run never passes. |
| `failed_record` | blocked | 1 | The newest matching record is `FAILED`. |
| `inconsistent_record` | blocked | 1 | A record fails its integrity check, and no intact record matches. |
| `committed_record` | blocked | 1 | The record is tracked by Git. A committed record can be hand-typed, so the gate never accepts one. |
| `local_record` | blocked | 1 | The record has no CI run identity. |
| `record_error` | cannot decide | 3 | A record path is missing, unreadable, not JSON, larger than 1 MiB or nested too deeply, or a record that fails its integrity check might be newer than the record the gate would decide on; the gate cannot decide without judging every record that might be the newest. |
| `config_error` | cannot decide | 3 | The configuration cannot be fingerprinted offline, for example because its routes come from catalogue discovery. |
| `repository_unknown` | cannot decide | 3 | Neither `--repository` nor `GITHUB_REPOSITORY` names this tree's repository, or they name different ones. |

The gate decides on the newest record from this repository that ran the
required selection and matches the current contract, routes and prompts, whatever its
verdict, so an older pass cannot hide a newer failure; on equal age, the
failure wins. A record that fails its integrity check cannot be judged, so
when its unproven date is missing or not older than that record, the gate
cannot decide. Only when no record matches does it explain the block with the
first applicable code among `committed_record`, `local_record`,
`foreign_record`, `inconsistent_record`, `selection_changed`,
`contract_changed`, `routes_changed` and `prompt_changed`.

## What the gate stops, and what it doesn't

The gate stops a pull request from merging on a record that is stale, from
another repository, committed to Git, written outside the CI run that made
its result, broken, or made for another contract, other routes, other prompts
or request options, or another selection. It does not stop a maintainer who
can change the workflows, approve their own paid run or edit the gate's
configuration, and it is only as strong as the place it runs:

- Make the gate workflow a required status check, and keep it out of the pull
  request's reach: require it with a repository ruleset or a required
  workflow, or require code-owner review for `.github/workflows/`. A pull
  request that can edit the gate workflow can make it pass.
- Keep the record workflow on protected branches and behind an environment
  with required reviewers. A record is only as trustworthy as the workflow
  that produced it.
- Accept records from `main` only. A record made on a pull request's own
  branch can come from a record workflow that branch edited and later
  restored. Where records are signed, verify them before the gate with
  `gh attestation verify RECORD --repo OWNER/REPO --signer-workflow
  OWNER/REPO/.github/workflows/llm-preflight-record.yml --source-ref
  refs/heads/main`, so only that workflow, run from `main`, can have
  produced them.

The gate compares everything a run sends, except credentials, and every
validator of the configuration: the contract, the routes, each prompt with its
request options, the selection and the repetitions per prompt. A route counts
each setting the client reads to build its requests: provider, model,
`adapter`, base URL, `api_version`, `max_tokens_parameter`, whether a
temperature is sent (as `supports_temperature`, `capabilities.temperature` and
the built-in model list decide it), the value of a behaviour header
(`anthropic-beta` and `anthropic-version`), the name of every other header,
and a mock route's `response`. Replacing the value of any other header,
including one that holds a credential under a name that is not a credential
key, does not change the route hash. Fingerprints hash text as written, so
prompts that differ only in a word that looks like a key, such as `sk-SK`,
never collide. A digest leaks nothing, so only values under credential names
are left out of it: `api_key`, `apikey`, `Authorization`, names ending in
`api-key` or `api_key`, and names with a `token`, `secret` or `password`
word, such as `x-auth-token`.

It leaves out settings that change neither what is sent nor how answers are
judged: warmups, which never count toward the decision, `concurrency`,
`stop_on`, `save_responses`, request and cost limits, prices, and a mock
route's simulated latency. Some settings that can change an outcome are left
out on purpose:

- `timeout_seconds` changes which slow requests fail, not what they ask.
- `api_key_env` and the credential itself choose the account a route uses; a
  record makes no claim about other accounts.
- A base URL's query string and fragment are dropped, because a query string
  can carry a key.
- The validators of the built-in test packs ship with llm-preflight, so a
  record attested by another version may have judged those tests by other
  rules; only their prompts and request options are compared.

## Private and public repositories

Every repository can use the unsigned flow. The
[Marketplace Action](../automation/github-action.md#proof-of-preflight) with
`attest: "true"` writes the record after an approved paid smoke and uploads it,
with its card, as the `llm-preflight-record` artifact. The result itself,
which holds the prompts, is not uploaded. The pull-request workflow in
[CI and JSON output](../automation/ci.md#proof-of-preflight-gate) downloads
the records of that workflow's recent runs on `main` and runs the gate. The
gate accepts a record because it is not committed and carries the identity of
the CI run that made its result; it does not check who started that run, so
keep the paid workflow behind a reviewed environment.

Public repositories, and private or internal ones on GitHub Enterprise Cloud,
can also sign the record. `sign: "true"` passes it to `actions/attest`, which
signs it with Sigstore through GitHub's artifact attestations. The calling job
needs `id-token: write` and `attestations: write`. `gh attestation verify`
with `--signer-workflow` then checks that the record workflow of this
repository produced exactly these bytes; run it before the gate, because the
gate itself does not check signatures. On other
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

1. `contract_changed`, `routes_changed` or `prompt_changed`: the pull request
   changed what the record checked, which is the gate working. Review the
   pull request's configuration, its routes and base URLs above all, and the
   plan with `llm-preflight benchmark.json --dry-run`. Then start the record
   workflow from `main` with the pull request's head commit as `commit`; that
   run sends the provider credentials wherever the configuration points.
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
   `--doctor` check reads the configuration for free. For a record that fails
   its integrity check, `llm-preflight verify` lists every problem; download
   it again intact or leave it out.
8. `repository_unknown`: outside GitHub Actions, add
   `--repository OWNER/NAME` for the repository the tree belongs to; in
   GitHub Actions, drop a `--repository` that names another repository.

Never make the gate pass by editing a record or the workflow. If the check
cannot pass for a reason you accept, say so in the pull request and let a
person decide.
