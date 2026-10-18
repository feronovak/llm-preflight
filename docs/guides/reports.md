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

Whole-run cost includes warmups. Missing prices or usage make total cost `n/a`;
any known cost is labelled an incomplete subtotal. Token subtotals also require
coverage and are shown as unavailable when incomplete. Retry attempts without
usage prevent completeness. Legacy schema-v1 artifacts without `cost_coverage`
remain unchanged on disk, but their cost is displayed as unverified rather
than a complete zero. Read the [result fields](../reference/results.md) for
machine-readable coverage semantics.

The renderer accepts schema-version-1 results and rejects unknown major
versions. It escapes displayed values and omits prompts, responses,
credentials, raw errors, custom run labels, local paths, host information, and
pricing source URLs. The page uses only inline CSS and performs no network
requests. It describes the measured workload and route; a small sample is not
a universal ranking.

## Preflight card

The card is a small SVG for a pull request, a release note or a README:

```bash
python3 -m llm_preflight report results/run.json --format svg --output card.svg
python3 -m llm_preflight report results/run.json --format svg \
  --record results/run.preflight.json --output card.svg
```

It looks the same every time on purpose: a white card, a black frame,
monospace numbers and one coloured verdict band. The band reads PASS (green),
INCONCLUSIVE (amber) or FAIL (red), and EXPIRED (grey) when the record given
with `--record` is older than 30 days or a route it checked has since retired.
The word carries the verdict, so the card reads the same in grayscale or
printed.

For each model the card shows the model and provider; the model the
provider's responses named ("Observed": every distinct name, marked
"responses disagreed", when they differed, and no row when none named one);
the probe count ("16 probes, all passed" or "13 of 16 passed", never a bare
percentage); p95 latency; the cost per 1,000 calls when the run's cost is
complete ("cost unknown" otherwise); and its status in the bundled
retirement snapshot. An
inconclusive card adds "Why:" with each blocking warning and "To pass:" with
the step that clears it; a failed card adds the failure reason. A record adds
its valid-until date and the repository whose CI run wrote it, or "none" for a
local record. Every card ends with the line "Does not certify:
accuracy · safety · production behaviour", the first 12 characters of the
result's evidence fingerprint, labelled `result evidence` because a record's
`llm-preflight/evidence` digest also seals the selection and the verdict,
and the `llm-preflight verify` command for the record.

The card is generated from saved evidence and is not evidence itself; keep the
record, not the picture. `--record` refuses a record that fails verification
or attests a different result file. Unlike the HTML and Markdown reports, the
card names the configuration (its `name`), so a shared card says which check
it shows; it omits prompts, responses, paths, run IDs and host details. A
control character in any name shows as its backslash escape, as `verify`
prints it. It is
deterministic for a given result, record and day, uses only system fonts,
and has an accessible title and description. See
[Proof of preflight](proof-of-preflight.md) for the record and the merge gate.

## Synthetic examples

The [report gallery](../../examples/reports/README.md) includes reproducible
fixtures for a schema regression, a cheaper candidate that fails its contract,
and a latency/cost regression against a comparable baseline. The fixtures are
source-checkout examples, are invented and labeled as synthetic, and are not
live provider evidence.

The Marketplace Action adds a no-spend check summary to each workflow job. If
the paid smoke is explicitly enabled, it appends the same privacy-filtered
result summary after the run.
