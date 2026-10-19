# Model retirements: the bundled snapshot and its verdict

**Last reviewed:** 2026-10-19 · **As of:** v2.22.2

Providers retire models on published schedules. llm-preflight bundles a
hand-reviewed snapshot of the official Anthropic, OpenAI and selected Gemini
deprecation/model pages
and reports, for every model ID it meets, whether that page lists it as
retired or retiring, the retirement date, and the replacement the provider
names. No network request is made; the snapshot ships with the package.

Run it on any repository, with no configuration file:

```bash
llm-preflight --audit-source .
```

```text
Decision: fail — 42 files audited; 57 model references: 6 retired, 2 retiring or stale, 31 unknown.
Exit 0 — add --ci to exit 1 on this decision.
Files: tracked by git, plus untracked files .gitignore does not exclude.
Retired:
  claude-3-haiku-20240307 (5 references) — retired <date>, replacement claude-haiku-4-5-20251001
    app/models.py:12
    app/summarize.py:40
    config/models.yaml:3
    2 more locations — use --all
    Next: llm-preflight --quick "<your prompt>" --models anthropic:claude-3-haiku-20240307,anthropic:claude-haiku-4-5-20251001 --dry-run
  gpt-4-32k (1 reference) — retired <date>, no single replacement recorded
    app/legacy.py:8
    Next: no single replacement recorded; read the page, choose one and preflight it (https://developers.openai.com/api/docs/deprecations)
Retiring or stale:
  gpt-4o (2 references) — retiring <date>, replacement gpt-6-luna
    app/chat.py:21
    tests/test_chat.py:9
    Next: llm-preflight --quick "<your prompt>" --models openai:gpt-4o,openai:gpt-6-luna --dry-run
Pricing unknown, no retirement finding: 14 references to 5 model IDs — use --all to list them.
```

The first line is the decision and the second the exit code it produces.
Findings follow, grouped by model ID: retired models first, then retiring or
stale ones, most-referenced first. The default output shows ten models and
three locations for each; `--all` prints every model and location, including
the references whose price is unknown but which have no retirement finding.
`--json` always contains every reference.

Inside a Git work tree the scan reads the files Git considers part of the
project: tracked files, including those of initialized submodules, plus
untracked files that `.gitignore` does not exclude. An untracked nested
repository that is not ignored is read as the filesystem walk would read it.
Outside a work tree, without Git, or when the work tree ignores the path
itself (a project inside a dotfiles repository that ignores `*`), it reads
every file under the path. Both modes skip `.git`, `.venv`, `venv`,
`node_modules`, `__pycache__` and `results` directories below the path; the
path itself may sit inside one. They read only `.py`, `.js`, `.mjs`, `.cjs`,
`.ts`, `.tsx`, `.json`, `.yaml`, `.yml` and `.toml` files, and never follow a
symlink out of the path. The `Files:` line and the JSON `file_selection` field
(`git`, `filesystem` or `file`) report the mode used; in `filesystem` mode the
line and `file_selection_reason` say why Git was not used.

Git runs without letting the audited repository run a command: its hooks,
file-system monitor, filter drivers and object fetching are disabled,
including in submodules. Global and system Git configuration still apply.

The same verdict appears in `--doctor` and `--dry-run` for the models a
configuration approves.

The bundled retirement rows were rechecked on **2026-10-19**. Their statuses,
retirement dates and replacements are unchanged. Non-retired rows become stale
on **2026-11-19** (day 31), and `--ci` then returns `3`; retired models still
return `1`. Pricing snapshots have their own review dates and expiry.

## Verdicts

| Status | Meaning | Decision |
|---|---|---|
| `retired` | The retirement date is today (UTC) or earlier, or the page lists the model as retired. | fail |
| `retiring` | A future retirement or deprecation is announced, including an alias redirected to another model without a shutdown date. | inconclusive |
| `stale` | The snapshot row was reviewed more than 30 days ago, counted in UTC days like the pricing snapshot. Update llm-preflight or read the official page. | inconclusive |
| `active` | The official page lists the model as active and the row is fresh. | pass |
| `unknown` | No snapshot row. Absence is not evidence. | none |

A stale row with a past retirement date is still `retired`; a date does not
age. Unknown is never a verdict: it covers every provider without a bundled
snapshot and every ID the pages do not list.

When no model is in the snapshot the aggregate decision is `none` and the exit
is 0; the scan prints `Decision: none` rather than pass, because nothing was
verified.

When the scan reads no file at all, the decision is `inconclusive` and
`--ci` exits 3: an audit that read nothing has no evidence. A selected file
that is not UTF-8 text, or that the user may not read, is not audited; the
output counts such files on a `Not audited:` line. The first line
says so and why, for example:

```text
Decision: inconclusive — nothing was audited: the path holds no source file outside skipped directories.
```

## Exit codes

Without `--ci` the scan and the dry-run exit 0 whatever they find, and the
doctor fails only on a `retired` model, as it does for any failed check. With
`--ci`, a `retired` model exits 1 and a `retiring` or `stale` model exits 3
in all three commands, and a scan that read no file exits 3.

The doctor fails a retired model without `--ci`, as it fails any configuration
check; pipelines running `--doctor` turn red on the retirement date. Rows go
stale 30 days after their review date (the bundled rows are stale from the 31st
day after the review date stamped above), after which `--ci` returns 3 for
every non-retired model in the snapshot (retired stays 1) until the package is
updated; models with no row stay at 0.

## Next steps

For a retired or retiring model with a provider-stated replacement, the output
prints one ready command that previews the switch without spending:

```text
Next:
  llm-preflight --quick "<your prompt>" --models openai:gpt-5.1,openai:gpt-6-sol --dry-run
```

Replace the prompt with the one your application sends. The replacement is
always the provider's own recommendation; llm-preflight never chooses one for
you. When the provider names none, names several, or names a model that is
itself being retired, no single replacement is recorded: the output says so
and points at the page instead of printing a command.

The doctor and the dry-run print the `Next:` block; the scan prints the same
command, or the page to read, as a `Next:` line under each model. The doctor
and the dry-run judge each model under the provider the configuration names, so
a routed ID under `openrouter` is unknown there; the scan infers the provider
from the ID.

## What the snapshot covers

- Anthropic: the model status table on the
  [model deprecations page](https://platform.claude.com/docs/en/about-claude/model-deprecations).
  Active models are listed, so `active` is evidence. Partner platforms
  (Bedrock, Vertex) set their own schedules and are not represented.
- OpenAI: the model entries on the
  [deprecations page](https://developers.openai.com/api/docs/deprecations).
  OpenAI publishes no active list, so an OpenAI ID absent from that page is
  `unknown`, not `active`.
- Gemini: five targeted rows from Google's
  [deprecations page](https://ai.google.dev/gemini-api/docs/deprecations) and
  [Gemini 4 Argon model page](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon).
  Gemini 4 Argon, 3.6 Flash and 3.8 Flash are active. The October 8
  [changelog](https://ai.google.dev/gemini-api/docs/changelog) confirms that
  3.5 Flash redirects to 3.6 and 3.7 to 3.8; these endpoints are not shutting
  down. The alias verdict explains the redirect and has no retirement date.
  Other Gemini IDs remain unknown; this is partial coverage.
- Text-generation models only. Audio, realtime, image, transcription,
  embedding and fine-tuning retirements are not in the snapshot.
- A page entry that names more than one replacement, a replacement that
  needs a request setting such as a reasoning mode, or a replacement that is
  itself deprecated or retired, is recorded without one.

## Release retirement review

The current snapshot contains 114 rows: 36 Anthropic, 73 OpenAI and five Gemini,
all reviewed on the date stamped above. The GPT-4o, GPT-4o mini, GPT-4.1 and
GPT-4.1 mini aliases follow the schedule of the dated snapshots their official
model pages name, and name `gpt-6-luna` as the page does. No row names the
retiring `gpt-4.1` or `gpt-4o` as a successor.

Before a release, a maintainer reads the official sources against
`llm_preflight/retirements.py`, updates changed rows, sets each reviewed row's
`as_of` to the review date, and updates the pinned rows and counts in
`tests/test_retirements.py` in the same change. The 30-day window is shorter
than Anthropic's 60-day minimum notice, so a fresh snapshot can vouch that no
retirement was announced before its review date.

To add a row, copy an existing `_anthropic(...)` or `_openai(...)` entry,
use the ID exactly as the page prints it, and record only a replacement the
page names on its own.
