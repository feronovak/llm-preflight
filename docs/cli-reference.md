# CLI reference

Run `llm-bench --help` for the installed version. The options below match this
release. `config` is a benchmark JSON path and is required unless `--init`,
`--quick`, `--diff`, or `--replay` is used.

| Option | Default | Purpose |
|---|---:|---|
| `--output-dir PATH` | `results` | Directory for saved result artifacts. |
| `--no-save` | off | Do not create result artifacts. |
| `--json` | off | Print the full result, plan, doctor report, or diff as JSON. |
| `--env NAME` | — | Apply a named configuration overlay. |
| `--smoke` | off | Set one repetition, no warmups, and concurrency one. |
| `--doctor` | off | Validate configuration, keys, and model resolution; no generation. |
| `--pricing-check` | off | Report unknown or stale prices; no generation. |
| `--baseline PATH` | — | Compare a completed run with a saved result. |
| `--ci` | off | Return exit code 1 if a requested baseline/diff regression fails. |
| `--matrix` | off | Print model-by-test quality matrix instead of the normal report. |
| `--quick TEXT` | — | Run one ad hoc prompt; requires `--models`. |
| `--init [PATH]` | `benchmark.json` | Create a no-key mock config without overwriting a file. |
| `--models LIST` | — | Comma-separated `provider:model` list for `--quick`. |
| `--diff BASELINE CURRENT` | — | Compare two saved JSON result files; no benchmark run. |
| `--replay PATH` | — | Re-run the saved source configuration in a result artifact. |
| `--changed-since PATH` | — | With discovery, run models absent from a prior catalog JSON. |
| `--catalog` | off | Discover and print selected models; no generation. |
| `--tests LIST` | — | Comma-separated built-in/custom test selector. |
| `--profiles LIST` | — | Compatibility alias for `--tests`. |
| `--dry-run` | off | Print resolved work and cost estimate; no generation. |
| `--no-env-file` | off | Do not load the adjacent `.env.production`. |
| `--env-file PATH` | — | Load this env file instead of the default adjacent file. |
| `--stop-on MODE` | — | Stop after `api-error`, `test-fail`, or `any-fail`. |
| `--fail-fast` | off | Compatibility alias for `--stop-on any-fail`. |
| `--prompt NAME` | — | Run one named custom prompt from the config. |
| `--interactive` | off | Select models, tests, repetitions, and stop mode in the terminal. |

## Compatible combinations

- `--json` works with benchmark results, `--dry-run`, `--doctor`, `--diff`,
  and `--catalog`. `--pricing-check` and `--catalog` always print JSON.
- `--ci` gates `--diff` and `--baseline`; ordinary benchmark failures already
  exit with status 1.
- `--smoke`, `--env`, `--tests`, `--dry-run`, `--json`, `--no-save`, and
  `--stop-on` can be combined with a normal config run.

## Incompatible combinations and requirements

- `--quick` requires `--models` and does not use a config file.
- `--init` cannot be combined with `config`.
- `--diff` runs alone; it compares its two positional JSON files.
- `--profiles` and `--tests` cannot be combined.
- `--profiles`/`--tests` cannot be combined with `--prompt`.
- `--interactive` cannot be combined with `--catalog`, `--profiles`,
  `--tests`, or `--prompt`.
- `--no-env-file` and `--env-file` are mutually exclusive.

Omit `--stop-on` to run every selected model. The interactive menu calls that
choice `never`; it is not a command-line value.
