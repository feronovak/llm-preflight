# GitHub Marketplace Action

Use the `v2.23.0` Action with `package-version: "2.23.0"` for reproducible CI.
The immutable release tag retains its earlier **2.22.2** default. An inconclusive paid decision remains exit 3; null cost
and incomplete subtotals remain visible in attached evidence.

**Last reviewed:** 2026-10-29 · **As of:** v2.23.0

`feronovak/llm-preflight` runs three no-spend checks by default: configuration
doctor, pricing coverage, and a bounded smoke dry-run. It is a local
contract-preflight gate, not an evaluation platform or deployment approval.

```yaml
steps:
  - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1
  - uses: feronovak/llm-preflight@v2.23.0
    with:
      config: benchmark.json
      package-version: "2.23.0"
```

The Action installs the exact `package-version` input. The current repository
source defaults to `2.23.0`; `v2.23.0` retains its `2.22.2` default. The `v2.22.1` release tag retains the `2.22.0`
default, so the example sets the input explicitly. The default execution path
makes no provider generation request and needs no secret. The action writes a
compact job summary confirming those three no-spend checks completed.

The repository's `Marketplace Action smoke` workflow explicitly pins a
published package to keep pull-request validation installable from PyPI.
Update that pin after each newer package is published and the workflow
succeeds against it.

## Paid smoke is opt-in

Only set `run-paid: "true"` after a person has reviewed the dry-run bounds and
approved the spend. Supply credentials through GitHub Secrets or an approved
environment; do not commit an environment file or put a key in action inputs.

```yaml
steps:
  - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1
  - uses: feronovak/llm-preflight@v2.23.0
    with:
      config: benchmark.json
      package-version: "2.23.0"
      run-paid: "true"
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

The paid path is a one-repetition smoke with no saved result. The action
temporarily captures its JSON result, appends the privacy-filtered report to
the GitHub job summary, then removes the temporary file. The summary omits
prompts, responses, credentials, paths, host details, and custom run labels.
Read the [agent decision contract](../reference/decision.md)
and [pricing and safety guide](../guides/pricing-and-safety.md) before using it
for a live integration change.

## Proof of preflight

From 2.22.0, two more inputs, both off by default, turn the paid smoke into a
record that a merge gate can check. With both off the Action behaves as
described above.

- `attest: "true"` needs `run-paid: "true"`. After the paid smoke it writes a
  [preflight record](../guides/proof-of-preflight.md) of the result and its
  SVG card, uploads both as the `llm-preflight-record` artifact, and links the
  artifact from the job summary. The result, which holds the prompts, is not
  uploaded. A failed or inconclusive run is recorded as such, and the step
  keeps the run's exit code. The paid smoke is a default `--smoke` run, one
  repetition per prompt, so the record's selection is `--smoke` and a gate
  for it takes `--smoke`. The record names the GitHub Actions run that made
  the result, and this repository is the only one whose gate counts it. Use
  `package-version` 2.22.0 or later: an older package's result records
  neither its selection nor its run, so the record is local and the gate
  never passes it.
- `sign: "true"` needs `attest: "true"`. It also signs the record with
  `actions/attest`, using the record's test-result predicate, so
  `gh attestation verify --signer-workflow` can check that this workflow, on
  the branch it ran on, produced it. The job needs `id-token: write` and `attestations: write`. Signing is
  available for public repositories, and for private or internal ones on
  GitHub Enterprise Cloud.

The Action pins `actions/upload-artifact` and `actions/attest` to commit
SHAs. This workflow records the contract on each push to `main`. For a pull
request that changes the contract, a maintainer starts it from `main` with
the pull request's head commit as `commit`; it then checks that commit's
configuration with the workflow and credentials of `main`. The protected
environment's required reviewers approve each paid run.

The workflow below uses `v2.23.0` with `package-version` `2.23.0`. The older `v2.22.1` release tag retains the `2.22.0` default; explicit package pins also make older tag behavior clear.

```yaml
name: LLM preflight record
on:
  push:
    branches: [main]
    paths: [benchmark.json]
  workflow_dispatch:
    inputs:
      commit:
        description: "Pull request head commit to record (empty: main)"
        required: false
permissions:
  contents: read
  id-token: write      # sign: "true" only
  attestations: write  # sign: "true" only
jobs:
  record:
    runs-on: ubuntu-latest
    environment: llm-preflight-paid  # required reviewers approve the spend
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1
        with:
          ref: ${{ inputs.commit || github.sha }}
          persist-credentials: false
      - uses: feronovak/llm-preflight@v2.23.0
        with:
          config: benchmark.json
          package-version: "2.23.0"
          run-paid: "true"
          attest: "true"
          sign: "true"
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

Save it as `.github/workflows/llm-preflight-record.yml`; the
[gate workflow](ci.md#proof-of-preflight-gate) looks for that file name and
counts only its runs on `main`. List every file that shapes the contract
under `paths`, such as prompt or schema files, or drop the filter. Drop `sign`
and both write permissions on a private repository without GitHub Enterprise
Cloud.

Review a pull request's configuration before you start a run with its
`commit`: that run sends the provider credentials wherever the pull request's
routes point. A changed `base_url` sends the key to another host, and a
changed `api_key_env` can send any variable of the job, such as the token the
signing step uses. Approve the environment only for a diff you have read.

A record is only as trustworthy as the workflow that produced it: whoever can
edit this workflow or approve the environment can produce a passing record.
Verify signed records with `gh attestation verify RECORD --repo OWNER/REPO
--signer-workflow OWNER/REPO/.github/workflows/llm-preflight-record.yml
--source-ref refs/heads/main`, as the
[gate workflow](ci.md#proof-of-preflight-gate) does; a dispatched run for a
pull request also runs from `main`.

It doesn't certify production behaviour. It proves the check was done.
