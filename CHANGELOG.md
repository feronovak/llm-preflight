# Changelog

All notable changes to this project are documented here.

## Unreleased

### Added

- MCP tool `audit_source`, the zero-config first step for an agent in a
  repository with no benchmark config. It returns the same object as
  `--audit-source --json`, with secret-like strings redacted as in every MCP
  tool result, so a path segment such as `sk-demo` reads `[REDACTED]`. It has
  the same `fail`, `inconclusive`, `pass` or `none` decision, and leads its
  text content with the CLI's first line. Its optional `path` is
  workspace-relative, defaults to the workspace root and keeps the existing
  workspace boundary, symlinks included. It is read-only,
  idempotent and closed-world: no credentials, no provider requests. The
  server instructions and the safe-workflow resource name it first.
- MCP tools `verify` and `gate`, bringing the server to seven tools. They
  return the same object as `verify --json` and `gate --json`, with
  secret-like strings redacted, and lead their text content with the CLI's
  first line; `verify` text now starts with
  `Verify: integrity …; freshness ….`. `gate` takes `records`, an optional
  `config` (default `benchmark.json`), `max_age_days` and the CI selection
  (`prompt`, `tests`, `environment`, `migration_check`). Every path, and every
  record or subject file found through it, must resolve inside the workspace.
  Both are read-only, idempotent and closed-world, and `attest` stays a CI
  step. The tool descriptions, server instructions, safe-workflow resource
  and plugin skill state that a gate `pass` is not approval of a model, a
  budget, a merge or paid work.
- A bounded three-request smoke example for native GLM 5.3, DeepSeek V4.1
  Flash and Qwen 3.8 Max, with deterministic streaming, usage and error
  checks. Native live results still require separate credentials and execution.
- Proof of preflight: `attest`, `verify` and `gate`. `attest RESULT` writes
  an in-toto Statement v1 with the test-result v0.1 predicate beside the
  result (`RESULT` with `.preflight.json`; `--output` overrides, `--force`
  replaces). It copies the saved decision (`PASSED`, `WARNED` or `FAILED`)
  and the provenance fingerprints, never upgrades the decision, and refuses a
  result without schema-version-1 provenance. In GitHub Actions it records the
  run identity and URL; elsewhere the record says `local`. `verify RECORD`
  reports integrity and freshness separately, prints its own
  retirement-snapshot date and states that signatures are checked with
  `gh attestation verify`, not here. `gate [CONFIG] --records PATH...` decides
  offline: it passes only on the newest GitHub Actions record that matches the
  current contract and routes and is `PASSED`, consistent, fresh
  (`--max-age-days`, default 30) and not superseded. It rejects records tracked
  by Git, never passes a local record, and exits 0 pass, 1 blocked, 3 when a
  config or record cannot be read or no repository is known. Text and `--json` carry the same reason
  code, why and numbered next steps. A record is untrusted input: integrity
  requires every route's provider, model and observed model to be a
  non-empty, printable string of at most 256 characters, and text output
  shows any control character in a record string or file name, a newline or
  an ANSI escape included, as its backslash escape, never raw. Existing
  commands and results are unchanged.
- `observed_model` in each saved model result and sample: the model the
  provider's responses said answered, read from the OpenAI-compatible
  `model` field (OpenAI, OpenRouter, xAI, DeepSeek, Qwen, Z.ai and custom
  endpoints), Anthropic's `message_start`, Gemini's `modelVersion` and the
  OpenAI Responses `model`. It is a string when the responses agree, the
  sorted distinct strings when they disagree, and `null` when none named a
  model; it is never filled in from the configured model. It is additive and
  outside `provenance`, so every fingerprint is unchanged. `attest` copies it
  into each route as `observedModel`, `verify` prints it on a `Route:` line
  and in `routes`, and the gate names it when it passes.
- Gate selection parity. Each new result records its run `selection`
  (`--prompt`, `--tests` or `--profiles`, `--env`, `--migration-check`, by
  name only) and `attest` copies it into the record. `gate` accepts the same
  flags and fingerprints the current config as a run under them would, so a
  record of a `--prompt`, `--env` or `--migration-check` run no longer reads
  as `contract_changed` or `routes_changed`. A record that ran a different
  selection, or records none, is blocked as `selection_changed`, naming both
  selections: the gate sets the bar, so a narrower run such as one cheap
  `--tests` choice cannot pass a gate that requires a default run. An env
  file only supplies credentials; neither its path nor its contents enter a
  result or a record.
- The gate counts only records from this repository. It takes the expected
  repository from `--repository OWNER/NAME`, else `GITHUB_REPOSITORY` on
  `GITHUB_SERVER_URL` (default `https://github.com`), and compares owner,
  name and host without regard to case, as GitHub does. A record from
  another repository or server is blocked as `foreign_record`, so a borrowed
  pass with the same fingerprints no longer counts. Without an expected
  repository the gate cannot decide (exit 3, `repository_unknown`) and names
  the `--repository` flag. `verify` shows the record's repository, and its
  JSON adds `repository` and `server_url`.

### Changed

- The OpenRouter GLM 5.3 comparison example carries the Relace route prices
  re-reviewed on 2026-10-16: $0.0608 input, $0.0565 cache reads and $4.40
  output per million tokens (previously $0.12, $0.12 and $4.00). Its maximum
  estimate is now $0.0361131392. Past measured costs are unchanged.
- `provenance.prompts` lists exactly the prompts a run sent, each once.
  Under `--prompt` it lists only the selected prompt; 2.21.x listed it twice,
  plus the configured prompts that did not run. A run of a configuration with
  both a top-level `prompt` and a `prompts` list lists only the top-level
  prompt. A profile run (`profiles`, `--tests`, `--profiles` or
  `--migration-check`) lists every case of the selected profiles, built-in
  ones included, and not the top-level prompt. `evidence_sha256` therefore
  differs from 2.21.x for these three run shapes; a run without profiles
  whose configuration has only a top-level prompt keeps identical provenance
  and hashes. Baseline
  comparison is unaffected: it uses the contract hash and validator version,
  which do not change.
- `--audit-source` text output now starts with the decision and its counts,
  then the exit code with and without `--ci`. Findings are grouped by model
  ID, retired first, with capped locations and one `Next:` line each.
  References with unknown pricing and no retirement finding collapse to one
  count. `--all` prints every model and location. `--json` is never capped and
  keeps its keys; it adds `file_selection` (`git`, `filesystem` or `file`),
  `file_selection_reason`, which says why Git did not select the files, and
  `files_unreadable`.
- Retirement snapshot re-reviewed against the official Anthropic, OpenAI and
  Gemini deprecation pages on October 16 UTC. No announcement since October 14
  affects it: all 114 rows keep their status, shutdown date and replacement.
  Non-retired rows now become stale on 2026-11-16, when their `--ci` verdict
  becomes inconclusive (exit 3). Retired rows continue to fail (exit 1).
- Pricing snapshots re-reviewed on 2026-10-16 UTC: all 39 bundled official
  rows were checked against their recorded provider pages. No price changed,
  including cache, long-context and scheduled Gemini rates. The rows now go
  stale from 2026-11-16 instead of from 2026-10-29. Qwen 3.8 cache-hit prices
  remain unknown.

### Fixed

- Native Qwen 3.8 Max, Max-0902 and Flash use `max_completion_tokens` by
  default so the output limit includes reasoning and the visible answer.
- A config whose `profiles` is a list, such as
  `["classification", "reasoning"]`, now passes the budget check and the
  `--dry-run` plan. Both turned the list into one text that named no profile
  and refused it; the run itself already accepted a list.
  An explicit legacy `max_tokens` model setting requires
  explicitly disabled thinking. OpenRouter requests are unchanged.
- Native Z.ai, DeepSeek and Qwen provider options cannot override the model,
  messages, streaming settings or token limits used by the planner. Doctor,
  budget estimation and transport reject these conflicting fields.
- Native Model Studio Qwen 3.8 Max/Flash cache-hit prices remain unknown
  until a reviewed account-specific override is supplied; QwenCloud cache
  rates are no longer substituted. Standard Singapore input/output prices
  were checked on October 15 and rechecked on October 16.
- `--audit-source` no longer reads gitignored files such as local worktrees,
  scratch directories and build output. Inside a Git work tree it audits
  tracked files, including initialized submodules, plus untracked files
  `.gitignore` does not exclude, including those of an untracked nested
  repository. Elsewhere, without Git, or when the work tree ignores the
  audited path itself, it reads every file under the path as before. A file
  name that is not UTF-8 does not turn `.gitignore` off. Symlinks that leave
  the audited path are never read. The decision for non-ignored files is
  unchanged.
- `--audit-source` never reports a clean result after reading no file. Such
  an audit is `inconclusive`, says that nothing was audited and why, and
  exits 3 under `--ci`; 2.21.x printed `Decision: none` and exited 0.
  `files_scanned` keeps its key but now counts only the files read as UTF-8
  text; files that are not, which 2.21.x counted as audited, are counted in
  `files_unreadable` and on a `Not audited:` line. So are files the user may
  not read; 2.21.x stopped the whole audit at the first one.
- `--audit-source` and `--change-plan` show a file or directory name that is
  not UTF-8 with backslash escapes, such as `bad\xff.py`, so text and JSON
  output stay valid UTF-8. 2.21.x wrote lone-surrogate escapes into the JSON,
  stopped the text output with an encoding error, and `--change-plan` failed.
- `--audit-source` skips `results`, `venv` and the other skipped directory
  names only below the audited path, so a project stored under such a
  directory is no longer audited as empty.
- When Git cannot list files, for example in a checkout Git considers of
  dubious ownership, the `Files:` line quotes Git's first error line instead
  of claiming the path is not a Git work tree.
- A retired model with no recorded date prints `retired (date not recorded)`
  rather than `retired date to be announced`.
- `--init` combined with `--all` is rejected like any other `--all` without
  `--audit-source`, instead of being ignored.
- The source audit's notes name the Gemini rows in the retirement snapshot
  alongside Anthropic and OpenAI.

### Security

- `--audit-source` and `--change-plan` no longer let the inspected
  repository's Git configuration run commands. Git runs with hooks, the
  file-system monitor, filter drivers and object fetching disabled, also in
  submodules, and without inherited variables that would point it at another
  repository. Global and system Git configuration still apply.

## 2.21.2 - 2026-10-14

### Fixed

- In 2.21.1, Claude Code and other strict MCP clients rejected the tool list
  on protocol `2026-07-28` because required cache metadata was missing. `tools/list`,
  `resources/list`, `resources/read` and `server/discover` now return
  `ttlMs: 0`, `cacheScope: "private"` and the complete-result marker. Legacy
  list/read responses keep their existing shape; no client configuration
  change is needed.

### Changed

- Replace homepage release-history prose with current workflows and a dated
  flagship/budget model table, including Opus 5.5, Haiku 5.5, GLM, DeepSeek
  and Qwen. Preserve recorded failures and identify Argon and other unmeasured
  candidates without transferring another model's result.
- Make the first-live-run instructions work from an installed CLI, with
  explicit accepted/rejected local fixtures before contract validation.

## 2.21.1 - 2026-10-14

### Fixed

- In 2.21.0, official MCP SDK clients could reject `validate_config` results
  for numeric, boolean, object or array configuration names because the
  advertised schema allowed only strings and null. The schema now matches all
  accepted JSON label types, preserving configured names and secret redaction.
- TestPyPI installation tolerates publication propagation with up to 40
  attempts and 39 waits of 15 seconds (585 seconds); success stops immediately
  and exhaustion still fails.
- Add regression coverage preserving the direct-provider replacement command
  when the same model ID is selected through a provider-less proxy, and pin
  the agent-guidance list item that requires reporting retirement decisions.
- Verify release freshness against the actual CLI pricing and source-audit
  commands at snapshot expiry and scheduled-price boundaries, including strict
  versus optional freshness for owner price overrides.
- Correct checkout pin comments to the exact v4.3.1 release; pinned commits
  and read-only workflow permissions are unchanged.

### Changed

- Point current repository Action and CI defaults at published 2.21.1. The
  immutable `v2.21.1` tag retains its 2.21.0 package default; set
  `package-version: "2.21.1"` explicitly when using it.
- Record the clarified build-rating-3 rubric and its revision reason, including
  separate build and publication verdicts and the PyPI UI yank procedure.
  Weights and the 40-checkpoint set are unchanged; historical reports retain
  their original rubric identifiers.
- Review all 114 retirement rows against official sources on October 14 UTC.
  Statuses, dates and replacements are unchanged. Non-retired rows become
  stale on 2026-11-14 (`--ci` exit 3); retired rows still fail (exit 1).
  Existing approval receipts mismatch because the retirement review date is
  part of the plan hash, including mock plans. Preview and approve again.

## 2.21.0 - 2026-10-14

### Added

- Add reviewed Gemini 4 Argon and Gemini 3.6 Flash prices, automatic published
  price transitions on December 1 and January 1, and a bounded Argon example
  with local contract fixtures. Native synchronous Argon requests have mocked
  protocol coverage, including thinking usage and implicit cache pricing.
- Add five targeted Gemini lifecycle rows and nine OpenAI GPT-4 dated/alias
  rows with the published January 14, 2027 shutdown and `gpt-6-luna` replacement.
- Guide interactive benchmark users through the shared CLI/MCP run plan and
  local contract fixtures, with explicit preview, config save, plan export,
  edit, mock-run and paid-run actions. Preview is the default; paid execution
  still needs a separate confirmation and budget review.
- Recover from invalid selections, search model lists with stable numbers,
  show selected counts, and support back navigation and cancellation.
- Export redacted selections without overwriting files, print a reproducible
  preview command, and show saved report/decision paths plus the offline HTML
  command after an interactive run.

### Fixed

- GPT-5.6 Luna/Terra/Sol and GPT-6 Astra/Sol/Luna now price reported cache
  writes at the published rates, including the full-request band above 272k
  input tokens. Plans include the possible write premium. Existing cache-read
  and input/output tier rates are unchanged.
- Gemini provider options cannot raise the output limit above the planned
  cap. Argon omits ignored sampling parameters and rejects explicit caching,
  unsupported thinking levels and synchronous caps above 65,536 before transport.
- Choosing "never" now removes an inherited stop rule and legacy `fail_fast`
  alias. Choosing the config prompt removes inherited profiles, so the preview
  and execution agree.
- `--interactive --dry-run` no longer asks to authorize execution or accept
  retry risk. Failed contract fixtures block the run action before any
  execution confirmation; missing fixtures remain explicitly unproven.
- Mock-only confirmation describes a local run. Interactive JSON sends menus,
  prompts and progress to stderr, and redirected output stays free of terminal
  control sequences. Configured-model preview, cancellation and mock runs do
  not load environment files; provider discovery may still need credentials.
- Config exports preserve output/tool schema property names and refuse to
  change validators or fixtures during redaction. Catalogue interactive review
  sends menus and prompts to stderr with `--json` and saves configs beside
  their source to preserve relative file references.

### Changed

- Review the retirement snapshot against official sources on October 13 UTC;
  it now has 114 rows across Anthropic, OpenAI and targeted Gemini models.
  Remove deprecated OpenAI successors from older replacement recommendations.
  Non-retired
  rows now become stale on 2026-11-13, when their `--ci` verdict becomes
  inconclusive (exit 3). Retired rows continue to fail (exit 1).
- Gemini 3.5/3.7 aliases report their redirects without a shutdown date and
  lose bundled/saved official prices; explicit owner prices retain precedence.
  Current smoke examples use Gemini 3.8 directly. September measurements
  remain historical; Gemini 4 has no live measurement in this release.
- Existing approval receipts report `mismatch` (exit 1) because their plan
  hashes include changed pricing and retirement snapshots, even for mock-only
  plans. Preview and approve the current plan again; receipt semantics and
  paid-run authorization rules are unchanged.
- Point the repository Action default, mock smoke workflow and CI examples at
  the published 2.21.0 package. The `v2.21.0` tag retains its 2.20.1 default;
  set `package-version` explicitly when using that tag.

## 2.20.1 - 2026-10-11

### Fixed

- MCP clients built on the official SDKs could not list the tools since
  2.10.0: the TypeScript SDK and Python SDK 2.x rejected every tool's output
  schema because it lacked a top-level object type. The schemas now declare
  it, and `dry_run_plan` declares its pricing warnings as objects, which
  Python SDK 1.x clients rejected for any plan with a pricing warning, such as
  one with a retired model.
- The MCP `dry_run_plan` tool now returns the same plan as the CLI
  `--dry-run --json`, plus `ok`, `pricing_ledger` and `pricing_fingerprint`.
  It gains `benchmark`, `tests`, `test_breakdown`, `request`, `presets`,
  `configuration_warnings`, `save_responses` and `stop_on`, and its `models`
  entries match the CLI, without the redacted `headers` map. The plan carries
  the same `retirements` report as the CLI, using the UTC date. `ok` is
  unchanged.
- For a retiring or retired model whose provider-named replacement is also in
  the plan, the JSON dry-run plan and the MCP plan now carry the "already in
  this plan" next step on that retirement entry, give it no `next_command`
  and leave it out of `next_commands`; the text plan prints the same step.
- The dry-run plan's `tests` and `test_breakdown` now follow a `profiles` key
  in the configuration; they reported the config prompt, one request per
  model, while `requests` already counted the profiles.
- Approval receipts written by an earlier version for a plan with such a
  retirement entry, or a configuration with a `profiles` key, now verify as
  `mismatch` (exit 1) because the plan they hash changed shape; run the
  dry-run again and re-approve them. Receipts for other plans still verify.
- The MCP safe-workflow resource and `initialize` instructions, the plugin
  skill, the MCP, coding-agent and AI implementation testing guides and the
  `init --agent-instructions` block tell agents to report the dry-run
  `retirements` decision: `fail` for a retired model, `inconclusive` for a
  retiring model or a stale snapshot row. The
  guide states that `ok` stays `true` for a retired model, and that
  `validate_config` checks structure without evaluating validation fixtures.
- `o1-preview` no longer records `o3` as its replacement: o3's only dated
  snapshot retires on 2026-12-11, so no replacement is recorded.
- Retirement docs and the 2.20.0 changelog state that snapshot rows reviewed
  2026-10-09 go stale from 2026-11-09 and that `--ci` then returns 3 for every
  non-retired model in the snapshot; retired models still return 1.
- Every README link, including the retirement guide, the license badge and
  the changelog, uses an absolute URL so the links work on the PyPI page.

### Changed

- The unit suite no longer depends on the wall clock: tests that check bundled
  example pricing pin the snapshot review day, and the new
  `make release-freshness` target, run by the release workflow before the
  build, runs `scripts/release_freshness.py` to check the same examples and
  the source audit on the real date. The script prints every failing example
  with its reasons, and `--today YYYY-MM-DD` replays another day.
- The PyPI publish action in the release and TestPyPI workflows and the
  checkout action in the project-standard workflow are pinned to commit SHAs.
- The contributor build rating is now `build-rating-2`: an independent rater,
  a named probe for every passing checkpoint, clock-shifted tests, mutants on
  critical paths, every user surface and every publication channel. The
  reason is recorded in `docs/DECISIONS.md`.
- Point the repository Action default, mock smoke workflow and CI examples at
  the published 2.20.0 package. The `v2.20.0` tag retains its 2.19.2 default;
  set `package-version` explicitly when using that tag. The Action's doctor
  step now fails a configuration that approves a retired model.

## 2.20.0 - 2026-10-10

### Added

- Bundled model retirement snapshot of the official Anthropic and OpenAI
  deprecation pages (`llm_preflight/retirements.py`) with a three-state
  verdict: retired fails, retiring or a stale row is inconclusive, unknown
  stays unknown. Replacements are provider-stated only.
- `--audit-source` attaches a `retirement` verdict to every reference, adds
  `decision` and ready `--quick --dry-run` `next_commands`, prints a `Next:`
  block, and exits 1 or 3 under `--ci`.
- `--doctor` fails a retired model and warns on a retiring or stale one;
  `--dry-run` lists retirement verdicts after eligibility. Under `--ci` both
  exit 1 for a retired model and 3 for a retiring or stale one.
- Guide: `docs/guides/retirements.md`, including the release retirement
  review.

### Changed

- Doctor output prints `warning:` instead of `ok:` for warning-severity
  checks, including pricing warnings.
- `--audit-source` confidence is `limited_static_pricing_and_retirement`.
- `--doctor` now fails, without `--ci`, a configuration that approves a model
  whose retirement date has passed; this includes the bundled Action's doctor
  step once pins move to this version. Many OpenAI rows in the bundled
  snapshot retire on 2026-10-23.
- Snapshot rows go stale 30 days after their review date (`as_of`, 2026-10-09
  in this release, so stale from 2026-11-09); from then `--ci` returns 3 for
  every non-retired model in the snapshot (retired stays 1) until the package
  is updated. Models with no row are unaffected.
- Scans whose references are all outside the snapshot report `decision: none`,
  not pass.
- Point the repository Action default, mock smoke workflow and CI examples at
  the published 2.19.2 package. The `v2.19.2` tag retains its 2.19.1 default;
  set `package-version` explicitly when using that tag.

## 2.19.2 - 2026-10-10

### Fixed

- Evaluate per-prompt `validation_fixtures` in `--contract-check`, in the
  pre-run fixture guard and in change-plan recommendations. Previously only
  top-level fixtures were checked, so a multi-prompt configuration's fixtures
  were never proven.
- Reject `validation_fixtures` that have no `validation` at the same level
  instead of checking them against the implicit non-empty rule.
- Scope `--prompt` to the selected prompt's own fixtures: a prompt with its own
  `validation` no longer inherits top-level `validation_fixtures`, which were
  checked against the wrong validator.

### Added

- Dry-run plans list each non-eligible model with its reason and next step,
  and state that eligibility gates `catalog prepare`, does not block a
  reviewed bounded run of text models, and that a live run refuses the models
  it lists as refused.
- Accepted and rejected fixtures in the bundled custom-contract examples.
- `--contract-check` reports prompts that declare a `validation` but no
  fixtures (`unproven_prompts`) and prints a note for each.

### Changed

- The README leads with the mission, the no-key demo and one failing
  contract; release notes live in this changelog.
- The configuration reference documents contract fixtures at both levels.
- Point the repository Action default, mock smoke workflow and CI examples at
  the published 2.19.1 package. The `v2.19.1` tag retains its 2.19.0 default;
  set `package-version` explicitly when using that tag.

## 2.19.1 - 2026-10-08

### Added

- Bundle Claude Haiku 5.5's reviewed input, output and cache-read pricing,
  including the higher full-request band above 100,000 total input tokens.
- Add bounded Anthropic 5.5 configurations for the original comparison cases,
  full built-in checks and a separate agent smoke.

### Fixed

- Omit unsupported `temperature` from native Claude Haiku 5.5 requests.
- Apply Claude Sonnet 5.5's October 7 cache-read price cut to $0.10 per
  million tokens, including configurations with persisted official snapshots.
- Normalize Anthropic input usage to include cache reads and writes, and
  retain reported cache-write usage. Writes without an explicit reviewed
  write rate make cost unavailable rather than silently understating it.

### Changed

- Update the README, documentation homepage and 27-model comparison with
  October 7 Haiku 5.5 and Sonnet 5.5 measurements, including the retained
  Haiku smoke failure and the separate request and cost totals.
- Point the repository Action default, smoke workflow, and CI examples at the
  published 2.19.0 package after the release.

## 2.19.0 - 2026-09-30

### Added

- Add native Z.ai GLM-5.3 chat with reviewed input/cache/output pricing,
  deterministic streaming and invalid-reasoning fixtures, source detection,
  OpenRouter discovery, and a bounded eight-case comparison example.
- List GLM-5.3 on the homepage and comparison table, and
  include it in maintained frontier and comparison examples.
- Include GPT-6.1 Sol in the OpenAI frontier candidate example and bundled
  official pricing snapshots, including its discounted cache and long-context
  rates.
- List GPT-6.1 Sol on the homepage and comparison table, and provide a
  bounded example of the eight-case study.
- Include GPT-6.1 Sol in automatic discovery and maintained comparison
  examples, with deterministic provider and pricing-boundary tests.

### Fixed

- Omit unsupported `temperature` from GPT-6.1 Sol requests.
- Preserve OpenAI's reported cache-write usage, price GPT-6.1 Sol's writes
  separately from reads, and include the write premium in its cost plan.
- Use current bundled prices in the flagship example instead of a stale
  Anthropic price override.
- Apply GPT-5.5's official cached-input rates and full-request price band
  above 272,000 input tokens, correcting long-context underestimates.
- Start Grok's long-context price band at 200,000 input tokens, matching
  the official inclusive threshold.

### Changed

- Add dated live comparison results: GPT-6.1 Sol passed 16/16 cases;
  GLM-5.3 through OpenRouter / Relace passed 14/16. Document the two
  validation failures, measured routes, latency, usage and estimated costs.

## 2.18.2 - 2026-09-28

### Fixed

- Bundle Claude Sonnet 5.5 and Haiku 4.5's official direct-provider prices so
  strict cost checks and estimates work for newly configured routes.
- Omit `temperature` from Claude Sonnet 5.5 requests because its API rejects
  nondefault sampling values.

### Added

- Include Claude Sonnet 5.5 in the priced frontier candidate example.

### Changed

- Point the repository Action default, smoke workflow, and CI examples at the
  published 2.18.1 package while preparing 2.18.2.
- Point the repository Action default, smoke workflow, and CI examples at the
  published 2.18.2 package after the release.

## 2.18.1 - 2026-09-28

### Fixed

- Preserve official native adapter and text-readiness metadata when enriching
  provider catalogue entries with OpenRouter capabilities.
- Pass configured system prompts to OpenAI Responses requests so contract
  checks exercise the intended instructions.

### Added

- Document a dated, scoped model comparison and list its measured models on
  the homepage without implying general model approval.

### Changed

- Point the repository Action default, smoke workflow, and CI starter at the
  published 2.18.0 package after the release.

## 2.18.0 - 2026-09-28

### Fixed

- Compare output-schema enum members recursively by JSON value type so numeric
  `1`/`0` cannot impersonate boolean `true`/`false` inside objects or arrays.
  Preserve numerical equivalence.
- Reject non-JSON `NaN` and `Infinity` constants and finite-range overflow in
  all structured-output parsing policies, including fields with no numeric
  schema rule. Reject decimal values that would round into a different number,
  and treat oversized integers as invalid output instead of raising a decoder
  exception. Prose parsing does not salvage nested values from a malformed
  outer value. Bind these corrections to validator semantics
  `output-schema-3` so earlier evidence is not treated as equivalent.
- Preserve missing or invalid provider usage as unavailable cost evidence;
  retain known subtotals and distinguish missing usage from missing prices.
  Include warmups when deciding completeness and reporting run cost.
- Apply strict pricing freshness to every billable source description and
  reject future review dates under the strict policy.
- Reject unsupported output-schema keywords and invalid rule combinations
  recursively before planning or provider requests; retain the separate
  canonical tool-schema subset.
- Preserve omitted Gemini output usage and avoid coercing malformed token
  counts into a valid estimate.
- Flag unverified cost completeness in legacy artifacts and suppress cost
  deltas or recommendations based on incomplete evidence. Retain known final
  response cost after retries while keeping unobserved retry usage unknown.

### Added

- Enforce boolean `additionalProperties` on output objects and inclusive finite
  `minimum`/`maximum` bounds on numeric outputs, including nested array items.
  Reject invalid rule combinations and non-finite numeric responses.
- Bind output-validator semantics to contract provenance. Different known
  semantics are incompatible; matching contract hashes without a semantics
  version have unknown comparability.
- Add a source-checkout application-owned configuration example with reviewed
  request/schema/config fixtures and tests for consumer drift. It does not
  execute application code through Preflight or establish pilot adoption.

### Changed

- Point the repository Action default, smoke check, and starter workflow at
  the published 2.17.1 package during release preparation.
- Recheck all 34 bundled public price snapshots on 2026-09-28 and link OpenAI
  rows to their model-specific official pricing pages. Qwen rows retain
  conservative USD list rates while a temporary discount is displayed.
- Refresh the synthetic report gallery with explicit invented cost/usage
  coverage so its intended decisions remain reproducible.

## 2.17.1 - 2026-09-25

### Added

- Add a project integration guide with an application contract, local fixtures,
  existing env-file reuse, report export, and a no-spend CI path.

### Changed

- Point the Marketplace Action default and no-spend CI examples at the
  published 2.17.0 package.
- Make MCP onboarding guidance explicit in its guide and safe-workflow resource.

## 2.17.0 - 2026-09-24

### Added

- Render saved schema-version-1 results as self-contained offline HTML or a
  compact, privacy-filtered GitHub Markdown job summary; unknown major schemas
  are rejected.
- Add synthetic report examples for a schema regression, a cheaper candidate
  that fails its contract, and a latency/cost baseline regression.
- Add no-spend and opt-in paid-run summaries to the Marketplace Action.
- Add the pre-merge report story and reproducible gallery to the README.

### Changed

- Update the GitHub Marketplace Action's default package version to the
  publicly available 2.16.0 release.
- Pass the Action's package-version input through the step environment instead
  of interpolating it into the shell script.
- Retry the Marketplace Action package install so a pin made just after
  publish is not failed by PyPI index lag.
- Document native routes, official pricing snapshots, and remaining gaps
  (Gemini 4, Kimi/GLM native, Jev) for package 2.16.0.

## 2.16.0 - 2026-09-22

### Added

- Add official pricing snapshots for GPT-6 Sol, GPT-6 Luna, Claude Opus 5.5,
  and Grok 4.7.

### Changed

- Point the frontier candidate example at the current GPT-6, Claude, and Grok
  flagship IDs. Gemini 4 still has no public API model ID or price table, so
  the Gemini rows stay on 3.1 Pro, 3.8 Flash, and 3.1 Flash-Lite. DeepSeek
  V4.1 Flash / V4 Pro and Qwen 3.8 remain the first-party Chinese routes we
  snapshot; Kimi and GLM stay OpenRouter or `openai_compatible` until a
  first-party adapter exists.

## 2.15.1 - 2026-09-20

### Changed

- Update the GitHub Marketplace Action's default package version to the
  publicly available 2.15.0 release.
- Refuse typed-decision and other non-text catalogue types on the text smoke
  path before any provider request, including OpenRouter `jev-*` rows.
- Enforce the CLI request and cost caps on MCP `run_preflight` live runs.
- Keep native `text-candidate` rows on the probe path when OpenRouter metadata
  claims they are text-ready.
- Count CJK characters as whole tokens in the pre-run cost cap so the spend
  gate does not under-count Qwen and other CJK prompts.

## 2.15.0 - 2026-09-20

### Added

- Add official pricing snapshots for GPT-6 Astra, Claude Fable 5.1, Gemini 3.8
  Flash, DeepSeek V4.1 Flash (`deepseek-flash`) and V4 Pro, Qwen 3.8 Max,
  Qwen 3.8 Flash, Qwen 3.7 Plus, and TypeSafe Jev.
- Add native `deepseek` and `qwen` catalogue/chat routes, and a `typesafe`
  catalogue route for Jev. Jev stays visible as a typed-decision model and is
  not eligible for the generic text smoke adapter. OpenRouter metadata cannot
  reclassify an official non-text catalogue type into a text smoke candidate.

### Changed

- Point the frontier candidate example at current public flagships: three
  models each from OpenAI, Anthropic, Gemini, xAI, and Qwen, plus DeepSeek's
  two live API IDs. Gemini 4 has no public API model ID or price table, so it
  is omitted.
- Default the native `qwen` route to the international DashScope
  compatible-mode endpoint so discovery and USD snapshots share one region.

## 2.14.0 - 2026-09-09

### Added

- Reuse an explicitly selected project env file from a benchmark configuration
  or provider starter. Shell values retain precedence; doctor reports only the
  credential source, never a credential value.

## 2.13.0 - 2026-09-08

### Added

- Add local image-input preflight support for image-to-text contracts on
  OpenRouter/OpenAI-compatible chat routes and Gemini. Inputs are constrained
  to verified local image fixtures; results retain metadata and a content hash,
  not image bytes.

## 2.12.0 - 2026-09-08

### Added

- Add no-spend `--contract-check` validation fixtures. A configured contract
  must prove both an accepted and a rejected response before its fixtures pass.
- Add strict, canonical tool-definition linting for name, description, and a
  portable JSON Schema parameter subset. It validates definitions but does not
  invoke tools or make provider requests.
- Add secret-safe result provenance: configuration, contract, resolved-route,
  pricing, and combined evidence fingerprints, prompt hashes, and declared
  request/cost caps.
- Add `--change-plan REF`, a Git-aware local report of changed, staged, and
  untracked files with literal model and contract-surface signals plus safe
  next commands. It never loads credentials, calls a provider, or authorizes
  paid work.
- Add expiring local dry-run approval receipts. They bind a human review note
  to a plan hash and its request/cost bounds, but are deliberately never
  accepted as paid-run authorization.

### Fixed

- Reject baseline comparisons with changed output-contract evidence or duplicate
  model names, and label legacy results without provenance as `unknown`.
- Include deleted files in Git-aware change-plan evidence and preserve existing
  parent-directory permissions when writing approval receipts.
- Give `catalog probe` the same explicit environment-file controls as benchmark
  commands.

### Changed

- Publish package classifiers and project URLs in wheel metadata, and clarify
  the README and north star around catching integration regressions.

## 2.10.0 - 2026-08-31

### Added

- Add standard MCP tool safety annotations, honest structured-output schemas,
  and a discoverable no-spend workflow resource for coding agents.
- Add a registry-ready `server.json` for the local PyPI stdio package, with a
  required `--workspace` filepath argument, plus a repository plugin skill that
  teaches the same no-spend workflow without adding a workspace command.
- Add TestPyPI clean-install coverage that starts the MCP server and reads its
  safe-workflow resource without credentials or provider traffic.

### Fixed

- Resolve the default config-adjacent `.env.production` through the same
  workspace-containment check as explicit paths, including symlink targets.
- Preserve an explicit `env_file` in the elicitation retry state so an
  approved paid-run retry uses the environment file the user selected.

## 2.9.0 - 2026-08-31

### Added

- Add a no-spend-by-default GitHub Marketplace Action: doctor, pricing, and
  bounded dry-run checks run automatically; a paid smoke requires an explicit
  action input and caller-provided credentials.
- Add safe provider-breakage and pricing-drift issue forms, plus a concise
  comparison page that keeps local contract preflight distinct from evaluation,
  observability, and provider administration.

### Changed

- Align GitHub repository metadata and README discovery with the local
  integration-change preflight niche: safe first run, workflow choices,
  explicit spend boundary, and a link to complete release history.

## 2.8.0 - 2026-08-31

### Added

- Add deterministic smoke-eligibility evidence that distinguishes eligible
  routes from models needing a probe, adapter evidence, compatible modality,
  current pricing, or bounded limits.
- Make `catalog prepare` retain only smoke-eligible models in its runnable
  candidate configuration, while keeping excluded models and their reasons in
  catalog refresh evidence.

## 2.7.5 - 2026-08-31

### Fixed

- Replace stale standard GPT-5.6 Luna, Terra, and Sol input/output rates from
  their primary source.
- Represent GPT-5.6 cached-input and long-context pricing, plus Grok 4.3
  cached-input and long-context pricing, in the shared pricing ledger.
- Remove the retired, unpriced `openrouter:minimax/minimax-m3` route and
  unpriced Gemini model from the tracked cross-provider examples.

### Changed

- Add a tracked frontier-candidate plan for current OpenAI, Anthropic, Gemini,
  and xAI models, including Grok 4.5 and Grok 4.6; keep it separate from the
  approved release smoke until compatibility evidence is retained.
- Assert every bundled pricing entry's reviewed rate, provider model ID,
  source URL, and review date in deterministic tests. The release review still
  verifies official provider documentation; the unit suite never fetches it.
- Add a tracked, fully priced approved smoke cohort and require its review
  before an owner-authorized paid release smoke.
- Align the README, package description, north star, product decisions, and
  pricing guide around the local contract-preflight scope.

## 2.7.4 - 2026-08-20

### Fixed

- Separate the human terminal decision state and blocking warnings from the
  executive ranking, so automation is directed to JSON or MCP evidence.

### Changed

- Clarify paid-run pricing enforcement, agent no-spend sequences, test-pack
  coverage, and the current GitHub Actions starter version in public docs.
- Derive legacy installer metadata from the package version and ship the PEP
  561 `py.typed` marker for typed consumers.

## 2.7.3 - 2026-08-20

### Fixed

- Require complete pricing across every configured tier before allowing a
  current-pricing gate to authorize a paid benchmark.
- Make unknown decision states fail closed and document exit code 3 for
  inconclusive evidence in the coding-agent guide.

## 2.7.2 - 2026-08-20

### Fixed

- Treat a model with complete per-request pricing tiers as priced for coverage
  and decision purposes, matching the estimator's tier selection.
- Omit the unsupported `temperature` parameter for `claude-opus-5` by default.
- Compact HTTP failures in the terminal quality gate so provider error bodies
  and request IDs do not expand report tables.
- Replace the retired `gemini-3.5-flash` in the cross-provider example and
  ignore generated `.llm-preflight/` workspace data.

## 2.7.1 - 2026-08-13

### Added

- Add an additive, independently versioned agent decision object with pass,
  fail, and inconclusive states; verbatim blocking warnings; and a safe next
  command in result JSON and MCP preflight responses.
- Add opt-in marker-delimited agent instruction blocks from `init`, including a
  non-mutating drift check.

### Changed

- Make mock-only results inconclusive, prevent model approval unless the whole
  result decision passes, and use exit code 3 for inconclusive evidence.
- Distinguish API failures from contract failures in agent decisions and point
  their safe next commands at setup diagnostics or a no-request plan review.

### Breaking

- A mock-only benchmark no longer exits successfully, and automation must
  distinguish exit code 3 (inconclusive) from exit code 1 (failed).

### Fixed

- Make the TestPyPI fresh-install smoke check accept the intentional exit code
  3 from its mock-only benchmark.

## 2.6.0 - 2026-08-11

### Added

- Add full selected-model pricing coverage with `priced`, `undated`, `stale`,
  and `unknown` states, stable machine-readable reason codes, and remediation.
- Record a primary source URL alongside each bundled direct-provider price
  snapshot entry.

### Changed

- Apply pricing freshness consistently to live-catalog and OpenRouter-routed
  prices, and to user overrides when `require_current_pricing` is enabled.
- Refresh the reviewed price snapshot, including correcting GPT-5.6 Luna from
  $1.00/$6.00 to $0.20/$1.20 and GPT-5.6 Terra from $2.50/$15.00 to
  $2.00/$12.00 per million input/output tokens.
- Exclude mock fixtures from billable-price summary counts.

### Fixed

- Keep duplicate configured model rows independent in `pricing-refresh`.
- Exempt deterministic `mock` fixtures from the paid-pricing gate while
  retaining them in coverage evidence.
- Refresh previously written direct-provider snapshot metadata when an upgraded
  package supplies a newer official snapshot.

## 2.5.0 - 2026-08-10

### Added

- Add `json_set` validation for unordered JSON arrays with duplicate rejection.
- Add `first_fenced_block` and `first_json_value` consumer policies for
  applications that intentionally select the first matching JSON payload.

### Changed

- Reject JSON Schema configurations with a missing or unsupported `type`, and
  ensure JSON booleans do not satisfy number or integer constraints.
- Warn when an Anthropic model is run with the `json` or `structured` preset:
  Anthropic does not receive an equivalent native JSON-mode request, so results
  are not directly comparable to providers that do.

## 2.4.3 - 2026-08-10

### Fixed

- Make the local MCP server interoperable with standard `initialize` clients,
  allowing Codex, Claude Code, and Cursor to discover and use the preflight
  tools.
- Resolve model aliases and provider presets for MCP configurations just as the
  CLI does, preventing valid preset configurations from terminating the MCP
  session.
- Support MCP `ping` requests.
- Do not load `.env.production` for mock or unconfirmed runs; credentials are
  loaded only for an explicitly confirmed live run.
- Return a standard-client `isError` result that names `confirm_paid_run` as
  the remedy when a live run lacks explicit confirmation.

### Changed

- Document copy-paste MCP setup for Codex, Claude Code, and Cursor, including
  the explicit approval boundary for paid preflight runs.

## 2.4.2 - 2026-08-02

### Fixed

- Restore compatibility with the repository's pinned CI Ruff release.

## 2.4.1 - 2026-08-02

### Fixed

- Preserve the recorded price ledger, including cached-input and tier pricing,
  when replaying a saved result.
- Add coverage that proves budget planning and result costing share the same
  resolved tiered/cached price evidence.

## 2.4.0 - 2026-08-02

### Added

- Add a local modern stdio MCP server with validate, dry-run, explicit-run, and
  baseline-diff tools.
- Add explicit OpenRouter live-catalog price refresh with user-override safety.

## 2.3.0 - 2026-08-02

### Added

- Add `llm-preflight init` with a no-key mock default and conservative explicit
  provider starter configurations that never write a secret.
- Add a fork-safe GitHub Actions preflight workflow example that pins its
  dependencies, uploads redacted evidence, and supports an optional baseline.

### Changed

- `init` is intentionally non-interactive in 2.3.0: it provides a deterministic
  mock default and explicit provider flags. Guided provider setup is deferred to
  a later release.

## 2.2.0 - 2026-08-01

### Added

- Add declared JSON consumer profiles (`raw_json`, `fenced_ok`, and
  `prose_tolerant`) and report contract-only failures when a stricter benchmark
  validator rejects a response accepted by the declared consumer.
- Add deterministic `golden` answer validation with per-profile accuracy and
  expected-versus-observed confusion counts.
- Add local-only `--audit-source PATH` for advisory literal model-ID and
  bundled-pricing findings with file and line evidence; it never imports
  application code or contacts providers.
- Add `priced_cost_usd`, `cost_confidence`, and `unpriced_models` while
  retaining the v1 all-or-null `total_estimated_cost_usd` contract.

### Fixed

- Fail a benchmark when its declared consumer parser rejects a response, and
  surface consumer rejections in terminal and Markdown contract diagnostics.
- Treat deeply nested JSON as invalid output rather than crashing a run.
- Emit the JSON result and embedded baseline comparison before `--baseline --ci
  --json` exits for a regression.

### Changed

- Clarify the product mission, vision, niche, and safe default validation
  workflow for coding agents.

## 2.1.1 - 2026-07-21

### Fixed

- Count Gemini thinking tokens as billable output tokens and apply cache-hit and
  long-context pricing tiers per request, including Gemini 3.1 Pro Preview's
  published 200k-input boundary.
- Keep `--json --baseline` machine-readable by embedding the comparison in the
  single JSON result document.
- Apply the same safe 256-token default output cap across provider clients.
- Fail comparison and recommendation gates for removed models, missing
  validation evidence, or zero-sample model results; deduplicate repeated test
  selectors before requests are planned.
- Refuse provider and catalog redirects, reject ambiguous unprefixed
  non-OpenAI quick-model IDs, load replay credentials from the recorded source
  config location, and preserve provider catalog order when dates are absent.

## 2.1.0 - 2026-07-21

### Added

- Add composable custom validation rules for JSON object or array shape, exact
  JSON array count, controlled values, numeric-only answers, maximum response
  length, and plain-text responses without Markdown formatting.
- Add curated, task-focused smoke packs for strict JSON extraction, support
  classification, code-patch summaries, source-grounded quizzes, and privacy
  boundaries. `agent-smoke` now selects this safe functional suite and excludes
  the opt-in concurrency load profile.

### Changed

- Document how to combine response contracts and how their parsing and
  comparison boundaries work.

## 2.0.5 - 2026-07-21

### Fixed

- Let `json_schema` contracts explicitly accept one Markdown-fenced JSON block
  when that matches the deployed consumer, while retaining raw JSON as the
  default and rejecting ambiguous multiple blocks or unfenced prose objects.
- Preserve the structured-response parsing policy in result samples and failure
  artifacts so a failed response can be interpreted against its real contract.

### Changed

- Document parser-aligned JSON contracts and include a deterministic
  fence-tolerant mock example.

## 2.0.4 - 2026-07-17

### Added

- Add `--version` to the main command.

## 2.0.3 - 2026-07-17

### Fixed

- Report `output_tokens_per_second` as unavailable when a provider delivers
  the response as a terminal burst rather than an incremental stream (fewer
  than two text chunks, or a generation window under 100 ms). Previously a
  buffered response — observed with Gemini — inflated throughput by orders of
  magnitude because the post-TTFT window measured transport, not generation.

### Changed

- README: add real cross-provider run output, a "How it compares" section,
  precise wording for the no-third-party-dependencies claim and deterministic
  validation, and absolute documentation links so the PyPI project page and
  sdist README no longer point at files excluded from the distribution.
- Remove the unused `_request_count` helper superseded by `estimate_budget`.
- Raise test coverage from 81% to 86% (316 tests) with new error-branch and
  validation tests across the runner, profiles, features, capability ledger,
  and environment modules.
- Mark the distribution as Beta (`Development Status :: 4 - Beta`).

## 2.0.2 - 2026-07-16

LLM Preflight is a local, cross-provider preflight CLI for validating a model
switch before it reaches production. It runs deterministic prompt validation
alongside latency, tokens, and cost across OpenAI, Anthropic, Gemini, xAI,
OpenRouter, and OpenAI-compatible providers.

The project now ships as a single package and command: `llm_preflight` /
`llm-preflight`. All compatibility surfaces from the earlier `llm-speed-bench`
/ `llm_bench` naming — the `llm-bench` command alias, the `llm_bench` import
namespace, and the legacy PyPI compatibility shim — have been removed.

## 2.0.1 - 2026-07-16

### Fixed

- Add the public `python3 -m llm_preflight` entry point for source checkouts
  and generated guidance; retain `python3 -m llm_bench.cli` as a legacy import
  path only.

## 2.0.0 - 2026-07-16

### Changed

- Rename the project and primary PyPI distribution to **LLM Preflight**
  (`llm-preflight`): a local, cross-provider preflight for a model switch.
- Make `llm-preflight` the primary command while retaining `llm-bench` and the
  `llm_bench` Python import namespace as supported compatibility interfaces.
- Update public documentation, examples, package artifacts, and release
  automation to use the new product name and primary command.

## 1.2.2 - 2026-07-16

### Fixed

- Keep plain-prompt validation results in model summaries, quality gates, and
  recommendation ranking so an invalid output can never pass or be recommended.
- Reject unknown validation keys and support explicit exact-match validation in
  ordinary and starter configurations.
- Calculate request and retry-expanded cost limits from every profile case,
  warmup, prompt override, and output limit.
- Preserve per-model results when client setup, runtime URL validation, or a
  request worker fails instead of aborting the benchmark.
- Keep transient catalogue probe failures retryable; only structured stable
  incompatibility evidence changes a model's catalogue classification.
- Measure successful request latency and time-to-first-token per final attempt,
  excluding retry backoff, and apply the same retry policy to Responses API
  requests.
- Gate CI comparisons on configured cost regressions, reject ambiguous custom
  prompt names and empty `contains` rules, and make numeric-only checks reject
  explanatory or contradictory output.
- Keep interactive catalogue comparisons head-to-head with selected approved
  models; require a distinct paid-run confirmation even after a stray `y` at
  the stop-mode prompt; preserve discovery deltas when a candidate run fails.
- Prefer authoritative ready-text catalogue evidence over model-name heuristics
  and redact Gemini and xAI key formats from all terminal, JSON, candidate-plan,
  and result output.
- Preserve transport retries by classifying socket failures by exception type;
  bootstrap a catalogue snapshot only after a successful first candidate run.
- Gate CI comparisons on validation-rate regressions as well as latency,
  request success, and cost; reject legacy built-in test aliases as custom
  prompt names.
- Keep `all` in catalogue review to the four inexpensive functional checks,
  protect invalid-scheme URL errors from credential echoes, and harden local
  workspace, exact-model-selection, approval-file, and query-encoding edges.

## 1.2.1 - 2026-07-16

### Fixed

- Keep the credential-free `.env.production` template created by `catalog init`
  identical to the checked-in `.env.example` template.

## 1.2.0 - 2026-07-16

### Added

- Add the local model lifecycle: `catalog init`, `catalog refresh`, and
  `catalog prepare`, followed by the normal interactive benchmark flow and
  explicit `models approve` promotion.
- Add local catalogue snapshots and model-change diffs; retain `watch-new` and
  `approve-model` as compatibility aliases.
- Add interactive `--approve-to` promotion, explicit retry-risk acceptance,
  and candidate-plan `--replace` protection.
- Classify catalogue entries as ready text benchmarks, text candidates needing
  one explicit probe, or incompatible generic-text endpoints using provider and
  OpenRouter capability evidence.
- Add `catalog probe` and a local, permission-restricted capability ledger that
  records only safe compatibility evidence, never response text or credentials.
- Add `--migration-check`: a one-repetition, no-warmup three-case response and
  basic-contract preflight for comparing a candidate model with an incumbent.
- Add a custom-contract tutorial and runnable mock examples for JSON extraction,
  exact intent routing, and required-content validation.
- Rename default test packs around their user value: quick migration, exact
  routing, structured output, numeric instruction, and concurrency health.
  Keep the former selectors as compatibility aliases.

### Fixed

- Refuse a concurrent benchmark targeting the same results directory before it
  can issue duplicate paid requests.
- Migrate legacy catalogue snapshots without reporting every model as changed
  solely because richer capability metadata was introduced.

## 1.0.3 - 2026-07-13

### Changed

- Keep internal agent, roadmap, launch, and release-runbook material out of
  public source distributions.
- Restrict source artifacts to runtime code, package metadata, user-facing
  documentation, and example configuration files.

## 1.0.2 - 2026-07-13

### Added

- Add `llm-bench --init` to create a safe, deterministic no-key mock benchmark
  without overwriting an existing configuration.
- Visually separate interactive setup stages and final terminal results,
  quality-gate, and decision sections.
- Render `--dry-run` as a readable terminal plan by default; retain JSON output
  with `--json` for automation.
- State the qualified recommendation explicitly and show the interactive
  command after `--init` creates a mock configuration.

### Fixed

- Exclude models that fail any selected test from fastest, cheapest, and
  best-value recommendations; list them with their failed test instead.
- Correct smoke-mode documentation: it reduces repetitions and warmups, but
  does not suppress selected profile-case or load-test expansion.

## 1.0.1 - 2026-07-13

### Fixed

- Handle Ctrl-C cleanly with exit code `130` and without writing artifacts.

## 1.0.0 - 2026-07-13

### Added

- Cross-provider smoke testing, discovery, deterministic validators, reports,
  pricing checks, retry diagnostics, and CI-oriented controls.
- A mock-provider quickstart and `--no-save` for no-key and CI workflows.
- Retry jitter plus nominal and retry-expanded request/cost planning.

### Security

- Redact all custom request-header values from result artifacts and output.
- Enforce configured cost ceilings only when complete pricing is available.

### Fixed

- Apply CLI `--tests` selections to budget enforcement.
- Keep the static type-check security gate green.
