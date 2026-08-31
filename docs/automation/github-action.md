# GitHub Marketplace Action

**Last reviewed:** 2026-08-31 · **As of:** v2.9.0

`feronovak/llm-preflight` runs three no-spend checks by default: configuration
doctor, pricing coverage, and a bounded smoke dry-run. It is a local
contract-preflight gate, not an evaluation platform or deployment approval.

```yaml
steps:
  - uses: actions/checkout@v4
  - uses: feronovak/llm-preflight@v2
    with:
      config: benchmark.json
```

The action installs the exact `package-version` input (default: `2.9.0`). Its
default path makes no provider generation request and needs no secret.

The repository's `Marketplace Action smoke` workflow intentionally pins the
last published package (`2.8.0`) while 2.9.0 is under development; that keeps
pull-request validation installable from PyPI. After 2.9.0 is published, update
that workflow pin to `2.9.0` and confirm the workflow succeeds again.

## Paid smoke is opt-in

Only set `run-paid: "true"` after a person has reviewed the dry-run bounds and
approved the spend. Supply credentials through GitHub Secrets or an approved
environment; do not commit an environment file or put a key in action inputs.

```yaml
steps:
  - uses: actions/checkout@v4
  - uses: feronovak/llm-preflight@v2
    with:
      config: benchmark.json
      run-paid: "true"
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

The paid path is a one-repetition smoke with no saved result. Retain evidence
through your workflow artifacts or local release process. Read the [North
star](../NORTH_STAR.md), [agent decision contract](../reference/decision.md),
and [pricing and safety guide](../guides/pricing-and-safety.md) before using it
for a live integration change.
