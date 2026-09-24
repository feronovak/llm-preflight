# Reviewable reports

**Last reviewed:** 2026-09-24 · **As of:** v2.17.0

From the repository root, render an existing result without repeating the
benchmark or contacting a provider:

```bash
python3 -m llm_preflight report results/run.json --output report.html
```

The standalone HTML opens offline. To print a compact GitHub-flavored Markdown
summary, use:

```bash
python3 -m llm_preflight report results/run.json --format markdown
```

The report starts with the run decision and, when present, a separate baseline
comparability and regression state. It then shows contract validity, request
count, latency, token usage, estimated cost, and pricing status/source/date.
The run decision is recomputed from the saved evidence; baseline regression
does not change that run decision.

The renderer accepts schema-version-1 results and rejects unknown major
versions. It escapes displayed values and omits prompts, responses,
credentials, raw errors, custom run labels, local paths, host information, and
pricing source URLs. The page uses only inline CSS and performs no network
requests. It describes the measured workload and route; a small sample is not
a universal ranking.

## Synthetic examples

The [report gallery](../../examples/reports/README.md) includes reproducible
fixtures for a schema regression, a cheaper candidate that fails its contract,
and a latency/cost regression against a comparable baseline. The fixtures are
source-checkout examples, are invented and labeled as synthetic, and are not
live provider evidence.

The Marketplace Action adds a no-spend check summary to each workflow job. If
the paid smoke is explicitly enabled, it appends the same privacy-filtered
result summary after the run.
