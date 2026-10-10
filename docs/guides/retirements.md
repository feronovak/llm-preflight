# Model retirements: the bundled snapshot and its verdict

**Last reviewed:** 2026-10-10 · **As of:** v2.20.0

Providers retire models on published schedules. llm-preflight bundles a
hand-reviewed snapshot of the official Anthropic and OpenAI deprecation pages
and reports, for every model ID it meets, whether that page lists it as
retired or retiring, the retirement date, and the replacement the provider
names. No network request is made; the snapshot ships with the package.

Run it on any repository, with no configuration file:

```bash
llm-preflight --audit-source .
```

The same verdict appears in `--doctor` and `--dry-run` for the models a
configuration approves.

## Verdicts

| Status | Meaning | Decision |
|---|---|---|
| `retired` | The retirement date is today or earlier, or the page lists the model as retired. | fail |
| `retiring` | A retirement is announced for a future date, or the model is deprecated with the date to be announced. | inconclusive |
| `stale` | The snapshot row was reviewed more than 30 days ago. Update llm-preflight or read the official page. | inconclusive |
| `active` | The official page lists the model as active and the row is fresh. | pass |
| `unknown` | No snapshot row. Absence is not evidence. | none |

A stale row with a past retirement date is still `retired`; a date does not
age. Unknown is never a verdict: it covers every provider without a bundled
snapshot and every ID the pages do not list.

## Exit codes

Without `--ci` the scan and the dry-run exit 0 whatever they find, and the
doctor fails only on a `retired` model, as it does for any failed check. With
`--ci`, a `retired` model exits 1 and a `retiring` or `stale` model exits 3
in all three commands.

## Next steps

For a retired or retiring model with a provider-stated replacement, the output
prints one ready command that previews the switch without spending:

```text
Next:
  llm-preflight --quick "<your prompt>" --models openai:gpt-5.1,openai:gpt-6-sol --dry-run
```

Replace the prompt with the one your application sends. When the provider
names no replacement, the output says so and points at the page. When the
named replacement is itself retiring or retired, the next step says that too.
The replacement is always the provider's own recommendation; llm-preflight
never chooses one for you.

## What the snapshot covers

- Anthropic: the model status table on the
  [model deprecations page](https://platform.claude.com/docs/en/about-claude/model-deprecations).
  Active models are listed, so `active` is evidence. Partner platforms
  (Bedrock, Vertex) set their own schedules and are not represented.
- OpenAI: the model entries on the
  [deprecations page](https://developers.openai.com/api/docs/deprecations).
  OpenAI publishes no active list, so an OpenAI ID absent from that page is
  `unknown`, not `active`.
- Text-generation models only. Audio, realtime, image, transcription,
  embedding and fine-tuning retirements are not in the snapshot.
- A page entry that names more than one replacement is recorded without one.

## Release retirement review

Before a release, a maintainer reads both official pages against
`llm_preflight/retirements.py`, updates changed rows, sets each reviewed row's
`as_of` to the review date, and updates the pinned rows and counts in
`tests/test_retirements.py` in the same change. The 30-day window is shorter
than Anthropic's 60-day minimum notice, so a fresh snapshot can vouch that no
retirement was announced before its review date.

To add a row, copy an existing `_anthropic(...)` or `_openai(...)` entry,
use the ID exactly as the page prints it, and record only a replacement the
page names on its own.
