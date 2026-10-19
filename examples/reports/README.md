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

## Try the merge gate without a provider

From the repository root, run this offline check. It reads the example
configuration and searches the gallery for CI records; it does not load
credentials or contact a provider:

```bash
python3 -m llm_preflight gate examples/project-integration/support-routing.json \
  --repository "${GITHUB_REPOSITORY:-acme/app}" --records examples/reports --json
```

Expected result: `decision: blocked`, `reason_code: no_record`, exit code `1`.
This nonzero exit is intentional. In a shell with `set -e`, run the command
on its own or handle that expected status before continuing.

A passing rendered report does not make this gate pass. These synthetic
fixtures carry no provenance and cannot be attested. A mock run also stays
inconclusive; neither is a substitute for a fresh passing CI record.

For a real contract, follow [proof of preflight](../../docs/guides/proof-of-preflight.md):
review the no-spend plan, explicitly approve the bounded live check, and
generate the record in the same CI run. Protect the record and gate workflows.
For signed records, run `gh attestation verify` before `gate`; the gate itself
does not authenticate signatures. No live run or CI setup is performed by
this gallery.

## Rebuild the README card

The README displays the failing synthetic fixture, rendered by the same CLI:

```bash
python3 -m llm_preflight report examples/reports/schema-break.json \
  --format svg --output docs/images/contract-break.svg
```

The card is an illustration of a contract failure. Its measurements are
invented, and its footer says it has no attested record. It is not a CI pass
or a case study of a production incident.
