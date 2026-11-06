# Model retirements: the bundled snapshot and its verdict

**Last reviewed:** 2026-11-04 · **As of:** v2.23.1

> The [Migrate report](#migrate-report) section describes the `migrate` command,
> which is not in 2.23.1 and is on the main branch only.

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
| `retiring` | A future retirement or deprecation is announced. An alias redirected to another model with no shutdown date is `active`, not `retiring`. | inconclusive |
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
- Gemini: six targeted rows from Google's
  [deprecations page](https://aistudio.google.com/docs/deprecations) and
  [Gemini 4 Argon model page](https://aistudio.google.com/docs/models/gemini-4-argon).
  Gemini 4 Argon, 3.6 Flash and 3.8 Flash are active. `gemini-3.5-flash` and
  `gemini-3.7-flash` are no longer available in Google AI Studio, but their
  endpoints are not shutting down: requests route to 3.6 Flash and 3.8 Flash.
  They are recorded active, and the verdict names the route; it has no
  retirement date and no replacement command. `gemini-3.1-flash-lite` is
  deprecated and retires on 2027-05-07; Google names `gemini-3.5-flash-lite`
  as its replacement. `gemini-3.1-pro-preview` has no row because the page
  states no shutdown date or replacement. Other Gemini IDs remain unknown;
  this is partial coverage.
- Text-generation models only. Audio, realtime, image, transcription,
  embedding and fine-tuning retirements are not in the snapshot.
- A page entry that names more than one replacement, a replacement that
  needs a request setting such as a reasoning mode, or a replacement that is
  itself deprecated or retired, is recorded without one.

## Release retirement review

The 2.23.1 snapshot contains 117 rows: 36 Anthropic, 75 OpenAI and six Gemini,
all reviewed on the date stamped above. Non-retired rows become stale on
2026-12-05; retired rows remain failures. The added dated OpenAI IDs
`gpt-5.4-nano-2026-03-17` and `gpt-5.1-2025-11-13` share the published
2027-04-01 retirement date of their aliases. The GPT-4o, GPT-4o mini, GPT-4.1 and
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

## Migrate report

Not in 2.23.1; on the main branch only.

`llm-preflight migrate CONFIG [--output PATH [--replace]] [--run] [--verify-approval-receipt PATH] [--ci] [--json]` reads the explicit `models` of a
benchmark config and reports which provider-named replacement applies to each
retired or retiring model. It never edits your config and makes no provider
request unless you pass `--run` with a recorded approval receipt; without `--output` it writes nothing. `discovery` is ignored with a
warning. Adopting a
replacement stays your step.

| Outcome | Meaning |
|---|---|
| `candidate` | One named replacement applies; use the printed `--quick --dry-run` command. A custom `api_key_env` is named, not copied: keep it when you add the model. |
| `replacement_in_config` | The replacement is already listed in your config on the same route (`base_url`). Run `--dry-run` on that config. |
| `no_named_replacement` | The row names none, or only one that needs a mode setting. Read the page. |
| `replacement_unusable` | The replacement is itself retired or retiring; the chain is not followed. |
| `snapshot_stale` | The row is older than 30 days, even when retired; update llm-preflight. The replacement's status is not reported. |
| `route_base_url` | The row sets a custom `base_url`. The provider names the replacement for its public route only, so add it by hand with your own prices and run `--dry-run` on that config. |
| `route_headers` | The row sets `headers`; add the replacement by hand. |
| `not_affected` | Active or unknown. |

### Candidate config

With `--output PATH`, `migrate` writes a candidate config next to the source
config (`PATH` must be in the same directory, so `prompt_file` and image paths
still resolve). It holds one row per replacement, deduplicated. A replacement
you already list is written as your own row, verbatim with your prices, unless
it sets `headers` or a custom `base_url` (a warning says to add it by hand).
Only a public `base_url` ever reaches the candidate, so a gateway row is never
copied or printed; write that config by hand. A new row copies only `provider`,
`base_url`, `api_key_env` and `api_version` from the old row, and a custom
`base_url` stops it as `route_base_url`. A warning names rows that share a
replacement but differ in `api_key_env` or `api_version`; the first row wins.
The `base_url` promise covers that field only: a URL in `name`, a prompt or
another setting is copied as written. Prices,
capabilities and token settings of the old model are dropped, `aliases`,
`environments` and `discovery` are left out, and the smoke settings, including
`save_responses`, are written into the file. Secret-shaped values are redacted
and reported as a warning. If two old rows share a replacement but name
different `api_key_env` values, the first row's key is used and a warning says
so. An existing `PATH` needs `--replace`, and `PATH` cannot be the source
config.

The report then adds the dry-run plan for the candidate (an `unbounded` plan
means a replacement has no bundled price: add it to your config with your own
rates and run `migrate` again), `approval` with state `missing`, and the
commands to record an approval receipt and to run the smoke. Nothing is run and
no provider is called yet.

### Run the smoke

1. `migrate CONFIG --output migrate.json` writes the candidate and prints the plan.
2. Record approval with the printed command (`--dry-run --approval-receipt ...`).
3. `migrate CONFIG --output migrate.json --run --verify-approval-receipt R` runs the smoke.

With `--run`, which needs `--output` pointing at the candidate already written, `migrate` runs the bounded smoke once, only if all hold: the candidate re-derived now equals the file on disk; the plan is rebuilt from that file the way `--dry-run` loads it; the receipt named by `--verify-approval-receipt` verifies as `recorded` with `bounds` equal to the plan's; `maximum_estimated_cost_usd` is not null; the budget check passes. Otherwise no env file is loaded and no provider is called. `--run` is the authorizing act: the receipt is a required precondition only and still has `authorizes_paid_run: false`. `--verify-approval-receipt` without `--run` only reports `approval.state` (`missing`, `recorded`, `expired`, `mismatch`, `invalid`, `candidate_changed` or `unbounded`); a missing or unreadable receipt is reported, not raised. After a smoke the report adds `smoke` and `paid_requests_made`, and the run's decision replaces the decision of each row whose replacement was written on the same route; a row that kept its own route (custom `base_url` or `headers`) keeps its decision. `--run` exits like `--ci`: 1 for `fail`, 3 for `inconclusive`. `--env-file`, `--no-env-file` and `--output-dir` apply to `--run` only; `--replace` cannot be combined with `--run`. A config with only `prompts` stops with `select a custom prompt before running the benchmark`. A budget excess, a config value of the wrong type (which can surface after a provider request was already sent; the message says so) and a config with only `prompts` stop with exit 2 and no report (nothing is printed under `--json`). `paid_requests_made` counts provider attempts sent, retries included, including a request the provider rejected with 401 or 403, and not a request that stopped for a missing API key. After a smoke, `next_steps` no longer offer the record or run commands: a `pass` says that adopting the replacement is your step, while `fail` or `inconclusive` give the reason and the saved result and say not to adopt it. The smoke writes only its result files. A candidate file that is absent or differs from the derived one reports `candidate_changed` and `next_steps` give the rewrite command (`migrate CONFIG --output PATH --replace`) instead.

`--doctor` and `--dry-run` print one `Next:` line pointing at `migrate` when they name a replacement to preview; it is text only and no JSON key changes.

A replacement the snapshot has no row for is reported as `unknown`, never as
active. With `--ci`, `migrate` exits 1 for a retired model and 3 for retiring or
stale; without it, 0. A bad config exits 2.

Over MCP, the read-only `migrate_plan` tool returns the same report with the
candidate config inline and redacted. It writes no file and runs no smoke, so an
agent saves `candidate_config.config` beside the source config before it uses
`validate_config`, `dry_run_plan` and, after approval, `run_preflight`. The
plugin entry and GitHub Action input do not offer `migrate`.
