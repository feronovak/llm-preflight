# Writing documentation

Write for an engineer maintaining an LLM feature or a reviewer assessing its
change. Start from their task: understand fit, run a first check, apply an
application rule, review evidence, automate, or recover from a failure.

## Give each page a job

The README explains fit, demonstrates a result, shows measured evidence and
offers one first run. The documentation homepage routes readers by task.
Tutorials provide a complete learning sequence; task guides provide required
inputs, steps, verification and recovery. Explanations describe mechanisms and
tradeoffs. Reference pages specify exact inputs, defaults, schemas and exits.

Before editing, identify the reader, their immediate question, the evidence
needed to answer it and the next action. Keep related paths linked rather than
repeating the same capability list across the page.

## Make results understandable

Name an application rule before using “contract” alone. Explain whether an
observed failure is a successful rejection, an API problem or missing evidence.
A mock test can pass while the benchmark is inconclusive. A local fixture
check evaluates the validator; it does not execute the application parser or
prove live-model behavior. State the specific result and the relevant limit.

Use plain verbs and concrete examples. Avoid unsupported adoption claims,
universal rankings, safety promises and claims that overlapping tools cannot
perform contract checks. Keep conditions next to the action they affect.

## Make examples executable

State the Python/package requirement and whether a command works from an
installed package or needs a source checkout. Supply the configuration or its
creation command. Preserve overwrite behavior, env-file precedence, output
retention and expected exit status when they affect the task.

Label paid commands before the code block. The direct CLI can send provider
requests without a separate approval prompt. MCP's confirmation boolean is not
proof of user consent; client approval and operating instructions matter.
The Action defaults to no generation requests. Do not describe all paths as
if they enforce the same approval mechanism.

For each procedure, include the expected observable result and a recovery path.
When an example deliberately returns nonzero, capture and check that specific
status instead of ignoring every error. A passing fixture is not a passing
production evidence gate.

## Keep evidence and visuals consistent

Measured observations retain dates, routes, request counts, failures and missing
values. A routed observation is not a native-provider test. Cost estimates are
not invoices; missing usage keeps totals unknown. Explain sample and latency
scope beside a summary and link the complete method.

Use the [visual asset specification](visual-assets.md) for fonts, colors,
dimensions and regeneration. The README measured table is an image, backed by
accessible text results in the comparison guide. Regenerate it from retained
evidence rather than editing displayed values. Preserve approved terminal
recordings when a prose change does not affect their behavior.

## Verify changes

- Execute relevant commands without provider keys where possible. Use mocked
  protocol fixtures for provider behavior; documentation work does not require
  paid traffic.
- Test meaningful outcomes and agreement with canonical data. Avoid freezing
  prose wording, line wrapping or arbitrary heading order in tests.
- Check local links, stable anchors, rendered image legibility and the
  installed-package/source-checkout distinction.
- Regenerate the document map after adding a tracked page:
  `python3 -m scripts.project_standard.cli generate`.
- Update affected review stamps only after reading the page against the source.
  Distinguish main-branch documentation from the last published package.
- Follow the [build evidence rubric](build-rating.md) for a reviewable build.
  At release time, verify the PyPI-rendered description; a repository push
  does not update it.

Where possible, ask someone unfamiliar with the edit to complete its task
without coaching. Retain observed blockers and correct them; a successful local
command alone does not establish that new readers understand the page.
