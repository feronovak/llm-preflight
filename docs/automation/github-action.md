# GitHub Marketplace Action

Use the `v2.25.4` Action with `package-version: "2.25.4"` for reproducible CI.
The immutable release tag retains its earlier **2.25.3** default. An inconclusive paid decision remains exit 3; null cost
and incomplete subtotals remain visible in attached evidence.

**Last reviewed:** 2026-11-11 · **As of:** v2.24.2

`feronovak/llm-preflight` runs three no-spend checks by default: configuration
doctor, pricing coverage, and a bounded smoke dry-run. It is a local
contract-preflight gate, not an evaluation platform or deployment approval.

```yaml
steps:
  - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1
  - uses: feronovak/llm-preflight@v2.25.4
    with:
      config: benchmark.json
      package-version: "2.25.4"
```

The Action installs the exact `package-version` input. The current repository
source defaults to `2.25.4`; `v2.25.4` retains its `2.25.3` default, `v2.25.3` retains its `2.25.2` default, `v2.25.2` retains its `2.25.1` default, `v2.25.1` retains its `2.25.0` default, `v2.25.0` retains its `2.24.2` default, `v2.24.2` retains its `2.24.1` default, `v2.24.1` its `2.24.0` default, `v2.24.0` its `2.23.1` default and `v2.23.1` its `2.23.0` default. The `v2.22.1` release tag retains the `2.22.0`
default, so the example sets the input explicitly. The default execution path
makes no provider generation request. For a non-mock config, the `--doctor`
step exits 1 when a model's key variable is unset, so supply each key variable
from a secret in the job's `env`; with `models` only, the checks need only the
variable to be present and send no request with it. With `discovery`, all three
checks send the key to that source's model-list endpoint (no generation
request), so the discovery `base_url` decides where the key goes. A mock config
needs no key. The action writes a
compact job summary confirming those three no-spend checks completed.

The repository's `Marketplace Action smoke` workflow explicitly pins a
published package to keep pull-request validation installable from PyPI.
Update that pin after each newer package is published and the workflow
succeeds against it.

## Keep the pin current

The bundled retirement rows go stale 30 days after their review date, and
then `--ci` returns `inconclusive` (exit 3) until you move to a newer release.
Official price rows follow the same 30-day rule from their own review dates.
The Action runs the doctor and dry-run with `--json` and without `--ci`, so it
prints no expiry notice and never exits 3 for a stale retirement row. A stale price row turns
it red through the `--pricing-check` step (exit 1). Run
`llm-preflight benchmark.json --doctor` locally or in your own CI to read
`snapshot.valid_until` (the oldest selected row's review date plus 30 days)
and the notice printed during its last 7 days.

Dependabot moves the Action tag but not the `package-version` input. A tag's
`action.yml` defaults to the package version of the release before it
(`v2.25.4` defaults to `2.25.3`), so a tag-only pin installs the previous
release and its data expires a release earlier. Keep `package-version` in
your workflow, set to the tag's version, and bump both together:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
```

```yaml
steps:
  - uses: feronovak/llm-preflight@v2.25.4
    with:
      config: benchmark.json
      package-version: "2.25.4"
```

Dependabot's pull request changes the tag; edit `package-version` in that pull
request to the same version.

## Paid smoke is opt-in

The action's dry-run step fails when a configured limit is broken, as the
CLI `--dry-run` exits 2 with the live run's error. Only set `run-paid: "true"`
after a person has reviewed the dry-run bounds and approved the spend. Supply credentials through GitHub Secrets or an approved
environment; do not commit an environment file or put a key in action inputs.

The optional `env-file` input names an environment file for the paid smoke and
is passed to `--env-file`. It has no effect on the no-spend checks; keep the
credentials in GitHub Secrets rather than in a file in the repository.

```yaml
steps:
  - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1
  - uses: feronovak/llm-preflight@v2.25.4
    with:
      config: benchmark.json
      package-version: "2.25.4"
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

The workflow below uses `v2.25.4` with `package-version` `2.25.4`. The older `v2.22.1` release tag retains the `2.22.0` default; explicit package pins also make older tag behavior clear.

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
      - uses: feronovak/llm-preflight@v2.25.4
        with:
          config: benchmark.json
          package-version: "2.25.4"
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
