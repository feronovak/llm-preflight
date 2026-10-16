# Reviewable report gallery

Run these commands from the root of a repository checkout. These
schema-version-1 result fixtures are synthetic. They contain no prompts,
responses, credentials, or live provider measurements. Rebuild the offline HTML
reports with the installed CLI:

```bash
python3 -m llm_preflight report examples/reports/schema-baseline.json \
  --output /tmp/schema-baseline.html
python3 -m llm_preflight report examples/reports/schema-break.json \
  --output /tmp/schema-break.html
python3 -m llm_preflight report examples/reports/cheaper-candidate-fails.json \
  --output /tmp/cheaper-candidate-fails.html
python3 -m llm_preflight report examples/reports/latency-cost-change.json \
  --output /tmp/latency-cost-change.html
```

Open each file in a browser. The first pair shows an accepted output changing
into a schema failure. The candidate report compares an incumbent with a
cheaper candidate that fails the same contract. The final report shows a
compatible baseline comparison that flags latency and cost regressions.

The same fixtures render as SVG preflight cards, a passing and a failing one
here:

```bash
python3 -m llm_preflight report examples/reports/schema-baseline.json \
  --format svg --output /tmp/schema-baseline.svg
python3 -m llm_preflight report examples/reports/cheaper-candidate-fails.json \
  --format svg --output /tmp/cheaper-candidate-fails.svg
```

The fixtures carry no provenance, so their cards show no evidence fingerprint
and they cannot be attested; the card's EXPIRED state needs a record.

All values are invented to demonstrate report behavior. They are not model
rankings, provider claims, or evidence from a paid run.
