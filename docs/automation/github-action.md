# GitHub Marketplace Action

**Last reviewed:** 2026-09-25 · **As of:** v2.17.1

`feronovak/llm-preflight` runs three no-spend checks by default: configuration
doctor, pricing coverage, and a bounded smoke dry-run. It is a local
contract-preflight gate, not an evaluation platform or deployment approval.

```yaml
steps:
  - uses: actions/checkout@v4
  - uses: feronovak/llm-preflight@v2.17.1
    with:
      config: benchmark.json
      package-version: "2.17.1"
```

The Action installs the exact `package-version` input. The current repository
source defaults to `2.17.1`. The `v2.17.1` release tag retains the `2.17.0`
default, so the example sets the input explicitly. The default execution path
makes no provider generation request and needs no secret. The action writes a
compact job summary confirming those three no-spend checks completed.

The repository's `Marketplace Action smoke` workflow pins the
latest published package (`2.17.1`), which keeps pull-request validation
installable from PyPI. Update that pin after each newer package is published
and the workflow succeeds against it.

## Paid smoke is opt-in

Only set `run-paid: "true"` after a person has reviewed the dry-run bounds and
approved the spend. Supply credentials through GitHub Secrets or an approved
environment; do not commit an environment file or put a key in action inputs.

```yaml
steps:
  - uses: actions/checkout@v4
  - uses: feronovak/llm-preflight@v2.17.1
    with:
      config: benchmark.json
      package-version: "2.17.1"
      run-paid: "true"
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

The paid path is a one-repetition smoke with no saved result. The action
temporarily captures its JSON result, appends the privacy-filtered report to
the GitHub job summary, then removes the temporary file. The summary omits
prompts, responses, credentials, paths, host details, and custom run labels.
Read the [North
star](../NORTH_STAR.md), [agent decision contract](../reference/decision.md),
and [pricing and safety guide](../guides/pricing-and-safety.md) before using it
for a live integration change.
